import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gui.mainframe as mainframe


class _DummyKeyEvent:
    def __init__(self, key, *, ctrl=False, shift=False, alt=False, meta=False):
        self._key = int(key)
        self._ctrl = bool(ctrl)
        self._shift = bool(shift)
        self._alt = bool(alt)
        self._meta = bool(meta)
        self.skipped = False

    def GetKeyCode(self):
        return int(self._key)

    def ControlDown(self):
        return bool(self._ctrl)

    def ShiftDown(self):
        return bool(self._shift)

    def AltDown(self):
        return bool(self._alt)

    def MetaDown(self):
        return bool(self._meta)

    def Skip(self):
        self.skipped = True


class _DummyTreeEvent:
    def __init__(self, item=object()):
        self._item = item
        self.skipped = False

    def GetItem(self):
        return self._item

    def Skip(self):
        self.skipped = True


class _DummyHost:
    on_char_hook = mainframe.MainFrame.on_char_hook
    on_article_list_key_down = mainframe.MainFrame.on_article_list_key_down
    _is_delete_key = mainframe.MainFrame._is_delete_key
    _is_backspace_key = mainframe.MainFrame._is_backspace_key
    _is_plain_backspace_event = mainframe.MainFrame._is_plain_backspace_event
    _is_shift_delete_event = mainframe.MainFrame._is_shift_delete_event
    _window_is_or_child = mainframe.MainFrame._window_is_or_child
    toggle_selected_article_read_status = mainframe.MainFrame.toggle_selected_article_read_status

    def __init__(self):
        self.tree = object()
        self.list_ctrl = object()
        self.player_window = None
        self._media_hotkeys = None
        self.calls = []
        self._focus = None
        self.selected_idx = 0
        self.current_articles = [
            mainframe.Article(
                title="Title",
                url="https://example.com/article",
                content="",
                date="",
                author="",
                feed_id="feed-1",
                id="article-1",
            )
        ]

    def _get_focused_window(self):
        return self._focus

    def on_edit_feed(self, event):
        self.calls.append(("edit_feed", event))

    def on_find_feed(self, event):
        self.calls.append(("find_feed", event))

    def on_delete_article(self, confirm=True):
        self.calls.append(("delete_article", bool(confirm)))

    def on_remove_feed(self, event):
        self.calls.append(("remove_feed", event))

    def on_article_activate(self, event):
        self.calls.append(("article_activate", event))

    def _make_list_activate_event(self, idx):
        self.calls.append(("make_list_evt", idx))
        return object()

    def _get_selected_article_index(self):
        return self.selected_idx

    def _is_load_more_row(self, idx):
        _ = idx
        return False

    def mark_article_read(self, idx):
        self.current_articles[idx].is_read = True
        self.calls.append(("mark_read", idx))

    def mark_article_unread(self, idx):
        self.current_articles[idx].is_read = False
        self.calls.append(("mark_unread", idx))


class _FakeMenuItem:
    def __init__(self, item_id, label):
        self._id = int(item_id)
        self.label = str(label)

    def GetId(self):
        return int(self._id)


class _FakeMenu:
    last_menu = None

    def __init__(self):
        self._next_id = 1000
        self._items = []
        self.submenus = []
        _FakeMenu.last_menu = self

    def Append(self, item_id, label, help_text=""):
        _ = help_text
        if int(item_id) == int(mainframe.wx.ID_ANY):
            item_id = self._next_id
            self._next_id += 1
        item = _FakeMenuItem(item_id, label)
        self._items.append(item)
        return item

    def AppendSeparator(self):
        return self.Append(mainframe.wx.ID_ANY, "---")

    def AppendSubMenu(self, submenu, label):
        item = self.Append(mainframe.wx.ID_ANY, label)
        self.submenus.append((str(label), submenu))
        return item

    def GetMenuItems(self):
        return list(self._items)

    def Destroy(self):
        pass


class _FakeProvider:
    def supports_article_delete(self):
        return True

    def supports_favorites(self):
        return False


class _FakeRect:
    def GetPosition(self):
        return mainframe.wx.Point(0, 0)


class _FakeListCtrl:
    def __init__(self):
        self.popup_menu = None
        self.popup_pos = None

    def GetFirstSelected(self):
        return 0

    def GetFocusedItem(self):
        return 0

    def GetItemRect(self, idx):
        _ = idx
        return _FakeRect()

    def PopupMenu(self, menu, pos):
        self.popup_menu = menu
        self.popup_pos = pos


class _DummyContextMenuHost:
    on_list_context_menu = mainframe.MainFrame.on_list_context_menu
    _get_selected_article_index = mainframe.MainFrame._get_selected_article_index
    _supports_article_delete = mainframe.MainFrame._supports_article_delete
    _supports_favorites = mainframe.MainFrame._supports_favorites
    _article_chapter_links = mainframe.MainFrame._article_chapter_links
    _validated_chapter_web_url = mainframe.MainFrame._validated_chapter_web_url
    _format_chapter_timestamp = mainframe.MainFrame._format_chapter_timestamp
    _format_player_chapter_menu_label = mainframe.MainFrame._format_player_chapter_menu_label

    def __init__(self):
        self.provider = _FakeProvider()
        self.list_ctrl = _FakeListCtrl()
        self.current_articles = [
            mainframe.Article(
                title="Title",
                url="https://example.com/article",
                content="",
                date="",
                author="",
                feed_id="feed-1",
                id="article-1",
            )
        ]
        self.bindings = []

    def _is_load_more_row(self, idx):
        _ = idx
        return False

    def Bind(self, evt, handler, item):
        self.bindings.append((evt, handler, int(item.GetId())))

    def on_article_activate(self, event):
        self.bindings.append(("activate", event, None))

    def _make_list_activate_event(self, idx):
        return ("activate", idx)

    def on_open_in_browser(self, idx):
        self.bindings.append(("browser", idx, None))

    def on_open_chapter_link(self, href):
        self.bindings.append(("chapter", href, None))

    def mark_article_read(self, idx):
        self.bindings.append(("read", idx, None))

    def mark_article_unread(self, idx):
        self.bindings.append(("unread", idx, None))

    def on_delete_article(self, confirm=True):
        self.bindings.append(("delete", bool(confirm), None))

    def on_copy_link(self, idx):
        self.bindings.append(("copy", idx, None))

    def on_detect_audio(self, article):
        self.bindings.append(("detect", article, None))


class _KeyboardContextEvent:
    def GetPosition(self):
        return mainframe.wx.DefaultPosition


class _FakeConfig:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class _TreeNavHost:
    on_tree_key_down = mainframe.MainFrame.on_tree_key_down
    on_tree_select = mainframe.MainFrame.on_tree_select
    _tree_selection_feed_id = mainframe.MainFrame._tree_selection_feed_id
    _is_tree_home_end_key = mainframe.MainFrame._is_tree_home_end_key
    _is_tree_navigation_key = mainframe.MainFrame._is_tree_navigation_key
    _should_defer_tree_selection = mainframe.MainFrame._should_defer_tree_selection
    _schedule_tree_selection_commit = mainframe.MainFrame._schedule_tree_selection_commit
    _cancel_tree_selection_commit = mainframe.MainFrame._cancel_tree_selection_commit
    _commit_pending_tree_selection = mainframe.MainFrame._commit_pending_tree_selection
    _commit_tree_selection = mainframe.MainFrame._commit_tree_selection

    def __init__(self):
        class _Tree:
            def __init__(self):
                self.selection = object()

            def GetSelection(self):
                return self.selection

        self.tree = _Tree()
        self._updating_tree = False
        self._unread_filter_enabled = False
        self._tree_selection_debounce_timer = None
        self._tree_selection_debounce_ms = 120
        self._tree_keyboard_nav_defer_until = 0.0
        self._tree_pending_feed_id = None
        self.current_feed_id = "all"
        self.config_manager = _FakeConfig({"remember_last_feed": True})
        self.selected_views = []
        self.feed_id_for_event = "feed-2"

    def _get_feed_id_from_tree_item(self, item):
        return self.feed_id_for_event

    def _select_view(self, feed_id):
        self.selected_views.append(feed_id)


def _install_fake_call_later(monkeypatch):
    scheduled = []

    class _FakeCallLater:
        def __init__(self, delay_ms, callback):
            self.delay_ms = delay_ms
            self.callback = callback
            self.stopped = False
            scheduled.append(self)

        def Stop(self):
            self.stopped = True

    monkeypatch.setattr(mainframe.wx, "CallLater", _FakeCallLater)
    return scheduled


class _DeleteHost:
    on_delete_article = mainframe.MainFrame.on_delete_article

    def __init__(self, *, confirm_setting=True):
        self.config_manager = _FakeConfig({"confirm_article_delete": confirm_setting})
        self.current_articles = [
            mainframe.Article(
                title="Title",
                url="https://example.com/article",
                content="",
                date="",
                author="",
                feed_id="feed-1",
                id="article-1",
            )
        ]

    def _get_selected_article_index(self):
        return 0

    def _is_load_more_row(self, idx):
        _ = idx
        return False

    def _supports_article_delete(self):
        return True

    def _fulltext_cache_key_for_article(self, article, idx):
        _ = article
        return (f"article:{idx}", "", str(idx))

    def _article_cache_id(self, article):
        return article.id

    def _delete_article_thread(self, *args):
        self.delete_thread_args = args


def test_f2_shortcut_opens_edit_feed_when_tree_focused():
    host = _DummyHost()
    host._focus = host.tree
    evt = _DummyKeyEvent(mainframe.wx.WXK_F2)

    host.on_char_hook(evt)

    assert ("edit_feed", None) in host.calls
    assert evt.skipped is False


def test_ctrl_shift_f_shortcut_opens_feed_search():
    host = _DummyHost()
    evt = _DummyKeyEvent(ord("F"), ctrl=True, shift=True)

    host.on_char_hook(evt)

    assert ("find_feed", None) in host.calls
    assert evt.skipped is False


def test_tree_home_end_selection_is_deferred(monkeypatch):
    scheduled = _install_fake_call_later(monkeypatch)
    host = _TreeNavHost()

    key_evt = _DummyKeyEvent(mainframe.wx.WXK_END)
    host.on_tree_key_down(key_evt)
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    assert key_evt.skipped is True
    assert host.selected_views == []
    assert host._tree_pending_feed_id == "feed-2"
    assert len(scheduled) == 1
    assert scheduled[0].delay_ms == 120

    scheduled[0].callback()

    assert host.selected_views == ["feed-2"]
    assert host.config_manager.get("last_selected_feed") == "feed-2"


def test_tree_arrow_selection_is_deferred(monkeypatch):
    # Up/Down arrow keydown must arm the defer window and route the ensuing
    # selection through the debounce timer, mirroring Home/End behavior so rapid
    # arrowing never commits a synchronous article load on every keystroke.
    for key in (mainframe.wx.WXK_UP, mainframe.wx.WXK_DOWN):
        scheduled = _install_fake_call_later(monkeypatch)
        host = _TreeNavHost()

        key_evt = _DummyKeyEvent(key)
        host.on_tree_key_down(key_evt)

        assert key_evt.skipped is True
        assert host._tree_keyboard_nav_defer_until > 0.0

        host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

        assert host.selected_views == []
        assert host._tree_pending_feed_id == "feed-2"
        assert len(scheduled) == 1
        assert scheduled[0].delay_ms == 120

        scheduled[0].callback()

        assert host.selected_views == ["feed-2"]
        assert host.config_manager.get("last_selected_feed") == "feed-2"


def test_tree_home_end_variants_mark_selection_for_defer():
    keys = [
        getattr(mainframe.wx, "WXK_HOME", None),
        getattr(mainframe.wx, "WXK_END", None),
        getattr(mainframe.wx, "WXK_NUMPAD_HOME", None),
        getattr(mainframe.wx, "WXK_NUMPAD_END", None),
    ]
    keys = [key for key in keys if key is not None]
    assert keys

    host = _TreeNavHost()
    for key in keys:
        host._tree_keyboard_nav_defer_until = 0.0
        evt = _DummyKeyEvent(key)

        host.on_tree_key_down(evt)

        assert evt.skipped is True
        assert host._is_tree_home_end_key(key) is True
        assert host._tree_keyboard_nav_defer_until > 0.0


def test_tree_navigation_variants_mark_selection_for_defer():
    keys = [
        getattr(mainframe.wx, "WXK_UP", None),
        getattr(mainframe.wx, "WXK_DOWN", None),
        getattr(mainframe.wx, "WXK_LEFT", None),
        getattr(mainframe.wx, "WXK_RIGHT", None),
        getattr(mainframe.wx, "WXK_PAGEUP", None),
        getattr(mainframe.wx, "WXK_PAGEDOWN", None),
        getattr(mainframe.wx, "WXK_NUMPAD_UP", None),
        getattr(mainframe.wx, "WXK_NUMPAD_DOWN", None),
        getattr(mainframe.wx, "WXK_NUMPAD_LEFT", None),
        getattr(mainframe.wx, "WXK_NUMPAD_RIGHT", None),
        getattr(mainframe.wx, "WXK_NUMPAD_PAGEUP", None),
        getattr(mainframe.wx, "WXK_NUMPAD_PAGEDOWN", None),
    ]
    keys = [key for key in keys if key is not None]
    assert keys

    host = _TreeNavHost()
    for key in keys:
        host._tree_keyboard_nav_defer_until = 0.0
        evt = _DummyKeyEvent(key)

        host.on_tree_key_down(evt)

        assert evt.skipped is True
        assert host._is_tree_navigation_key(key) is True
        assert host._tree_keyboard_nav_defer_until > 0.0


def test_modified_tree_home_end_is_not_deferred():
    host = _TreeNavHost()

    for evt in (
        _DummyKeyEvent(mainframe.wx.WXK_END, ctrl=True),
        _DummyKeyEvent(mainframe.wx.WXK_END, shift=True),
        _DummyKeyEvent(mainframe.wx.WXK_HOME, alt=True),
    ):
        host._tree_keyboard_nav_defer_until = 0.0

        host.on_tree_key_down(evt)

        assert evt.skipped is True
        assert host._tree_keyboard_nav_defer_until == 0.0


def test_tree_home_end_second_selection_cancels_first_timer(monkeypatch):
    scheduled = _install_fake_call_later(monkeypatch)
    host = _TreeNavHost()
    host.current_feed_id = "feed-start"
    host.on_tree_key_down(_DummyKeyEvent(mainframe.wx.WXK_END))

    host.feed_id_for_event = "feed-end"
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))
    host.feed_id_for_event = "feed-home"
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    assert len(scheduled) == 2
    assert scheduled[0].stopped is True
    assert host.selected_views == []

    scheduled[1].callback()

    assert host.selected_views == ["feed-home"]
    assert host.config_manager.get("last_selected_feed") == "feed-home"


def test_tree_rapid_arrow_navigation_commits_only_final_selection(monkeypatch):
    # Rapid arrowing: each arrow keydown re-arms the defer window and each
    # resulting selection reschedules the commit, stopping the prior timer, so
    # only the final resting selection ever renders (one commit, not per keystroke).
    scheduled = _install_fake_call_later(monkeypatch)
    host = _TreeNavHost()
    host.current_feed_id = "feed-start"

    host.on_tree_key_down(_DummyKeyEvent(mainframe.wx.WXK_DOWN))
    host.feed_id_for_event = "feed-a"
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    host.on_tree_key_down(_DummyKeyEvent(mainframe.wx.WXK_DOWN))
    host.feed_id_for_event = "feed-b"
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    assert len(scheduled) == 2
    assert scheduled[0].stopped is True
    assert host.selected_views == []

    scheduled[1].callback()

    assert host.selected_views == ["feed-b"]
    assert host.config_manager.get("last_selected_feed") == "feed-b"


def test_tree_mouse_click_selection_commits_immediately(monkeypatch):
    # A selection with NO preceding navigation keydown (mouse click or
    # programmatic selection) never sets a defer window, so it must commit
    # synchronously without scheduling a CallLater.
    def _unexpected_call_later(*args, **kwargs):
        raise AssertionError("mouse-click tree selection should not schedule CallLater")

    monkeypatch.setattr(mainframe.wx, "CallLater", _unexpected_call_later)
    host = _TreeNavHost()

    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    assert host.selected_views == ["feed-2"]
    assert host.config_manager.get("last_selected_feed") == "feed-2"
    assert host._tree_pending_feed_id is None


def test_tree_arrow_keydown_before_selection_defers_commit(monkeypatch):
    # Companion to the mouse-click case: the same selection, but preceded by an
    # arrow keydown, must be deferred through the debounce timer rather than
    # committing immediately.
    scheduled = _install_fake_call_later(monkeypatch)
    host = _TreeNavHost()

    host.on_tree_key_down(_DummyKeyEvent(mainframe.wx.WXK_UP))
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    assert host.selected_views == []
    assert host._tree_pending_feed_id == "feed-2"
    assert len(scheduled) == 1

    scheduled[0].callback()

    assert host.selected_views == ["feed-2"]
    assert host.config_manager.get("last_selected_feed") == "feed-2"


def test_tree_pending_selection_is_not_committed_if_tree_selection_changed(monkeypatch):
    scheduled = _install_fake_call_later(monkeypatch)
    host = _TreeNavHost()
    host.feed_id_for_event = "feed-end"
    host.on_tree_key_down(_DummyKeyEvent(mainframe.wx.WXK_END))
    host.on_tree_select(_DummyTreeEvent(host.tree.GetSelection()))

    host.feed_id_for_event = "feed-home"
    scheduled[0].callback()

    assert host.selected_views == []
    assert host.config_manager.get("last_selected_feed") is None


def test_tree_selection_feed_id_applies_unread_filter():
    host = _TreeNavHost()
    host._unread_filter_enabled = True

    assert host._tree_selection_feed_id(host.tree.GetSelection()) == "unread:feed-2"


def test_delete_shortcut_deletes_article_when_list_focused():
    host = _DummyHost()
    host._focus = host.list_ctrl
    evt = _DummyKeyEvent(mainframe.wx.WXK_DELETE)

    host.on_char_hook(evt)

    assert ("delete_article", True) in host.calls
    assert evt.skipped is False


def test_article_list_key_down_deletes_article():
    host = _DummyHost()
    evt = _DummyKeyEvent(mainframe.wx.WXK_DELETE)

    host.on_article_list_key_down(evt)

    assert ("delete_article", True) in host.calls
    assert evt.skipped is False


def test_shift_delete_shortcut_deletes_article_without_confirmation():
    host = _DummyHost()
    evt = _DummyKeyEvent(mainframe.wx.WXK_DELETE, shift=True)

    host.on_article_list_key_down(evt)

    assert ("delete_article", False) in host.calls
    assert evt.skipped is False


def test_backspace_toggles_unread_article_to_read():
    host = _DummyHost()
    host.current_articles[0].is_read = False
    evt = _DummyKeyEvent(getattr(mainframe.wx, "WXK_BACK", 8))

    host.on_article_list_key_down(evt)

    assert ("mark_read", 0) in host.calls
    assert host.current_articles[0].is_read is True
    assert evt.skipped is False


def test_backspace_toggles_read_article_to_unread():
    host = _DummyHost()
    host.current_articles[0].is_read = True
    evt = _DummyKeyEvent(getattr(mainframe.wx, "WXK_BACK", 8))

    host.on_article_list_key_down(evt)

    assert ("mark_unread", 0) in host.calls
    assert host.current_articles[0].is_read is False
    assert evt.skipped is False


def test_global_backspace_toggles_article_when_list_focused():
    host = _DummyHost()
    host._focus = host.list_ctrl
    host.current_articles[0].is_read = False
    evt = _DummyKeyEvent(getattr(mainframe.wx, "WXK_BACK", 8))

    host.on_char_hook(evt)

    assert ("mark_read", 0) in host.calls
    assert evt.skipped is False


def test_article_context_menu_includes_delete_for_supported_provider(monkeypatch):
    monkeypatch.setattr(mainframe.wx, "Menu", _FakeMenu)
    host = _DummyContextMenuHost()

    host.on_list_context_menu(_KeyboardContextEvent())

    labels = [item.label for item in host.list_ctrl.popup_menu.GetMenuItems()]
    assert "Delete Article\tDel" in labels
    assert "Mark as &Read" in labels
    assert "Mark as &Unread" in labels
    assert "View Feed Description..." in labels


def test_article_context_menu_exposes_accessible_chapter_link_commands(monkeypatch):
    monkeypatch.setattr(mainframe.wx, "Menu", _FakeMenu)
    host = _DummyContextMenuHost()
    host.current_articles[0].chapters = [
        {"start": 65, "title": "Details", "href": "/chapters/details"}
    ]

    host.on_list_context_menu(_KeyboardContextEvent())

    parent_menu = host.list_ctrl.popup_menu
    assert "Chapter Links" in [item.label for item in parent_menu.GetMenuItems()]
    chapter_menu = parent_menu.submenus[0][1]
    assert [item.label for item in chapter_menu.GetMenuItems()] == ["Open 01:05, Details"]


def test_delete_article_skips_confirmation_when_setting_disabled(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append((self.target, self.args, self.daemon))

    def fail_message_box(*_args, **_kwargs):
        raise AssertionError("delete confirmation should not be shown")

    monkeypatch.setattr(mainframe.wx, "MessageBox", fail_message_box)
    monkeypatch.setattr(mainframe.threading, "Thread", FakeThread)

    host = _DeleteHost(confirm_setting=False)
    host.on_delete_article()

    assert len(started) == 1
    assert started[0][1] == ("article-1", "article-1", "article:0")


def test_delete_article_can_explicitly_bypass_confirmation(monkeypatch):
    started = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append((self.target, self.args, self.daemon))

    def fail_message_box(*_args, **_kwargs):
        raise AssertionError("explicit confirmation bypass should not show a dialog")

    monkeypatch.setattr(mainframe.wx, "MessageBox", fail_message_box)
    monkeypatch.setattr(mainframe.threading, "Thread", FakeThread)

    host = _DeleteHost(confirm_setting=True)
    host.on_delete_article(confirm=False)

    assert len(started) == 1


def test_delete_article_keeps_confirmation_by_default(monkeypatch):
    started = []
    prompts = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            self.target = target
            self.args = args
            self.daemon = daemon

        def start(self):
            started.append((self.target, self.args, self.daemon))

    def message_box(*args, **_kwargs):
        prompts.append(args)
        return mainframe.wx.NO

    monkeypatch.setattr(mainframe.wx, "MessageBox", message_box)
    monkeypatch.setattr(mainframe.threading, "Thread", FakeThread)

    host = _DeleteHost(confirm_setting=True)
    host.on_delete_article()

    assert prompts
    assert not started
