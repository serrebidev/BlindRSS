# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from types import SimpleNamespace

import gui.mainframe as mainframe


class _ListCtrl:
    def __init__(self):
        self.labels = {}
        self.focused = -1
        self.count = 0

    def SetItem(self, idx, column, label):
        self.labels[(int(idx), int(column))] = str(label)

    def GetFocusedItem(self):
        return self.focused

    def GetItemCount(self):
        return self.count


class _ContentCtrl:
    def __init__(self, value="Article body", insertion_point=3, selection=(1, 4)):
        self.value = value
        self.insertion_point = insertion_point
        self.selection = selection

    def GetValue(self):
        return self.value

    def AppendText(self, text):
        self.value += text
        self.insertion_point = len(self.value)
        self.selection = (self.insertion_point, self.insertion_point)

    def SetValue(self, text):
        self.value = str(text)
        self.insertion_point = 0
        self.selection = (0, 0)

    def GetInsertionPoint(self):
        return self.insertion_point

    def SetInsertionPoint(self, insertion_point):
        self.insertion_point = int(insertion_point)

    def GetSelection(self):
        return self.selection

    def SetSelection(self, start, end):
        self.selection = (int(start), int(end))

    def GetParent(self):
        return None


class _Player:
    def __init__(self, current_article_id=None, current_chapters=None, same_media=False):
        self.current_article_id = current_article_id
        self.current_chapters = list(current_chapters or [])
        self.same_media = bool(same_media)
        self.updated = []
        self.loaded = []
        self.paused = 0

    def update_chapters(self, chapters):
        self.current_chapters = list(chapters or [])
        self.updated.append(list(chapters or []))

    def is_current_media(self, article_id, media_url):
        _ = article_id, media_url
        return self.same_media

    def is_audio_playing(self):
        return True

    def pause(self):
        self.paused += 1

    def load_media(self, media_url, use_ytdlp, chapters, **kwargs):
        self.loaded.append((media_url, use_ytdlp, chapters, kwargs))


class _Config:
    def get(self, _key, default=None):
        return default


class _ChapterHost:
    _article_cache_id = mainframe.MainFrame._article_cache_id
    _get_display_title = mainframe.MainFrame._get_display_title
    _format_chapter_timestamp = mainframe.MainFrame._format_chapter_timestamp
    _format_article_chapters_text = mainframe.MainFrame._format_article_chapters_text
    _compose_article_reader_text = mainframe.MainFrame._compose_article_reader_text
    _set_article_reader_text = mainframe.MainFrame._set_article_reader_text
    _remove_trailing_article_chapters_text = mainframe.MainFrame._remove_trailing_article_chapters_text
    _validated_chapter_web_url = mainframe.MainFrame._validated_chapter_web_url
    _article_chapter_links = mainframe.MainFrame._article_chapter_links
    on_open_chapter_link = mainframe.MainFrame.on_open_chapter_link
    _cache_article_chapters = mainframe.MainFrame._cache_article_chapters
    _update_article_chapter_indicator = mainframe.MainFrame._update_article_chapter_indicator
    _flush_deferred_title_cells = mainframe.MainFrame._flush_deferred_title_cells
    _flush_deferred_status_cells = mainframe.MainFrame._flush_deferred_status_cells
    _window_is_or_child = mainframe.MainFrame._window_is_or_child
    on_article_select = mainframe.MainFrame.on_article_select
    _is_load_more_row = mainframe.MainFrame._is_load_more_row
    _invalidate_reader_text_tracking = mainframe.MainFrame._invalidate_reader_text_tracking
    _append_chapters = mainframe.MainFrame._append_chapters
    _apply_chapters_for_player = mainframe.MainFrame._apply_chapters_for_player
    _open_article = mainframe.MainFrame._open_article

    def __init__(self, article, player):
        self.current_articles = [article]
        self._base_articles = [article]
        self.view_cache = {}
        self.list_ctrl = _ListCtrl()
        self.content_ctrl = _ContentCtrl()
        self.selected_article_id = self._article_cache_id(article)
        self.player_window = player
        self.config_manager = _Config()
        self.visibility = []
        self.focused_window = None
        self._updating_list = False
        self._fulltext_token = 0

    def _get_focused_window(self):
        return self.focused_window

    def _rich_view_active(self):
        return False

    def _update_content_view(self, _idx):
        return None

    def _ensure_player_window(self):
        return self.player_window

    def _should_play_in_player(self, _article):
        return True

    def _playback_target_for_article(self, article):
        return article.media_url, False

    def toggle_player_visibility(self, force_show=None):
        self.visibility.append(force_show)

    def _fetch_chapters_for_player(self, *_args, **_kwargs):
        return None


def _article(article_id="article-1", chapters=None, url="https://example.com/episode"):
    return SimpleNamespace(
        id=article_id,
        cache_id=f"feed:{article_id}",
        title="Episode",
        chapters=list(chapters or []),
        media_url="https://example.com/audio.mp3",
        media_type="audio/mpeg",
        url=url,
    )


def test_article_title_announces_chapter_availability():
    article = _article(chapters=[{"start": 0.0, "title": "Intro"}])
    host = _ChapterHost(article, _Player())

    assert host._get_display_title(article) == "Episode, Chapters available"


def test_append_chapters_updates_indicator_and_preserves_reader_selection():
    article = _article()
    host = _ChapterHost(article, _Player())
    chapters = [{"start": 3723.9, "title": "Discussion", "href": "https://example.com/chapter"}]

    host._append_chapters(article.cache_id, chapters)

    assert article.chapters == chapters
    assert host.list_ctrl.labels[(0, 0)] == "Episode, Chapters available"
    assert "Chapters (1):" in host.content_ctrl.value
    assert "1:02:03, Discussion. Link: https://example.com/chapter" in host.content_ctrl.value
    assert host.content_ctrl.selection == (1, 4)


def _two_row_host():
    first = _article("article-1")
    second = _article("article-2")
    second.title = "Other episode"
    host = _ChapterHost(first, _Player())
    host.current_articles = [first, second]
    host.list_ctrl.count = 2
    host.focused_window = host.list_ctrl
    return host, first, second


def test_chapters_for_the_focused_row_wait_until_focus_moves():
    # Column 0 is the row's accessible name: rewriting it on the focused row
    # makes NVDA read the whole row again while the user is listening to it.
    host, first, _second = _two_row_host()
    host.list_ctrl.focused = 0
    chapters = [{"start": 0.0, "title": "Intro"}]

    host._append_chapters(first.cache_id, chapters)

    assert first.chapters == chapters
    assert host.list_ctrl.labels == {}

    # The same row selected again: still focused, so still nothing.
    host._flush_deferred_title_cells()
    assert host.list_ctrl.labels == {}

    # The user arrows to the next row: the first row now gets its indicator.
    host.list_ctrl.focused = 1
    host._flush_deferred_title_cells()
    assert host.list_ctrl.labels == {(0, 0): "Episode, Chapters available"}

    # Applied once only.
    host.list_ctrl.labels.clear()
    host._flush_deferred_title_cells()
    assert host.list_ctrl.labels == {}
    assert host._deferred_title_cells == set()


def test_selecting_another_row_writes_the_deferred_title_after_the_handler(monkeypatch):
    # The listview fires the new row's focus event only after the selection
    # event returns. A title written inside on_article_select reaches NVDA
    # while the row being left is still its focus object, and NVDA reads that
    # row again; the write must wait for a posted callback.
    posted = []
    monkeypatch.setattr(mainframe.wx, "CallAfter", lambda fn, *a, **k: posted.append((fn, a, k)))
    monkeypatch.setattr(mainframe.wx, "CallLater", lambda _ms, fn, *a, **k: posted.append((fn, a, k)))
    host, first, _second = _two_row_host()
    host.list_ctrl.focused = 0
    first.chapters = [{"start": 0.0, "title": "Intro"}]
    host._update_article_chapter_indicator(first.cache_id)

    host.list_ctrl.focused = 1
    host.on_article_select(SimpleNamespace(GetIndex=lambda: 1))

    assert host.list_ctrl.labels == {}
    assert posted

    for fn, args, kwargs in posted:
        fn(*args, **kwargs)

    assert host.list_ctrl.labels == {(0, 0): "Episode, Chapters available"}


def test_chapters_for_an_unfocused_row_update_its_title_at_once():
    host, first, _second = _two_row_host()
    host.list_ctrl.focused = 1
    first.chapters = [{"start": 0.0, "title": "Intro"}]

    host._update_article_chapter_indicator(first.cache_id)

    assert host.list_ctrl.labels == {(0, 0): "Episode, Chapters available"}
    assert not getattr(host, "_deferred_title_cells", None)


def test_focused_row_title_updates_at_once_when_the_list_is_not_focused():
    # NVDA only reads name changes of its focus object. With focus in the
    # reader, holding the title back would only hide it, e.g. from the row a
    # later Tab into the list lands on.
    host, first, _second = _two_row_host()
    host.list_ctrl.focused = 0
    host.focused_window = host.content_ctrl
    first.chapters = [{"start": 0.0, "title": "Intro"}]

    host._update_article_chapter_indicator(first.cache_id)

    assert host.list_ctrl.labels == {(0, 0): "Episode, Chapters available"}
    assert not getattr(host, "_deferred_title_cells", None)


def test_deferred_title_follows_the_article_when_rows_shift():
    host, first, second = _two_row_host()
    host.list_ctrl.focused = 0
    first.chapters = [{"start": 0.0, "title": "Intro"}]
    host._update_article_chapter_indicator(first.cache_id)
    assert host.list_ctrl.labels == {}

    # A refresh merged a newer item above it: the article moved down a row and
    # the new one now sits where it was. The title goes to the article's new row.
    newer = _article("article-0")
    newer.title = "Newer episode"
    host.current_articles = [newer, first, second]
    host.list_ctrl.count = 3
    host.list_ctrl.focused = 0
    host._flush_deferred_title_cells()

    assert host.list_ctrl.labels == {(1, 0): "Episode, Chapters available"}


def test_deferred_title_for_an_article_that_left_the_view_is_dropped():
    host, first, second = _two_row_host()
    host.list_ctrl.focused = 0
    first.chapters = [{"start": 0.0, "title": "Intro"}]
    host._update_article_chapter_indicator(first.cache_id)

    # Another view is shown; the article keeps its chapters for the next render.
    host.current_articles = [second]
    host._flush_deferred_title_cells()

    assert host.list_ctrl.labels == {}
    assert host._deferred_title_cells == set()


def test_youtube_chapter_completion_does_not_rebuild_reader_text():
    article = _article(url="https://www.youtube.com/watch?v=abcDEF12345")
    host = _ChapterHost(article, _Player())
    original = host.content_ctrl.value
    chapters = [{"start": 60, "title": "Second section"}]

    host._append_chapters(article.cache_id, chapters)

    assert article.chapters == chapters
    assert host.list_ctrl.labels[(0, 0)] == "Episode, Chapters available"
    assert host.content_ctrl.value == original
    assert host.content_ctrl.selection == (1, 4)


def test_async_fulltext_reader_update_preserves_chapter_section():
    chapters = [{"start": 12, "title": "Opening", "href": "https://example.com/opening"}]
    article = _article(chapters=chapters)
    host = _ChapterHost(article, _Player())

    displayed = host._set_article_reader_text(article, "FULL ARTICLE", reset_insertion=True)

    assert displayed == host.content_ctrl.value
    assert displayed.startswith("FULL ARTICLE")
    assert "Chapters (1):" in displayed
    assert "00:12, Opening. Link: https://example.com/opening" in displayed
    assert host.content_ctrl.insertion_point == 0


def test_chapter_refresh_replaces_old_reader_section_without_duplication():
    old_chapters = [{"start": 0, "title": "Old"}]
    article = _article(chapters=old_chapters)
    host = _ChapterHost(article, _Player())
    host.content_ctrl.value = host._compose_article_reader_text("Article body", article=article)
    host.content_ctrl.selection = (1, 4)
    new_chapters = [{"start": 30, "title": "New"}]

    host._append_chapters(article.cache_id, new_chapters)

    assert host.content_ctrl.value.count("Chapters (1):") == 1
    assert "00:30, New" in host.content_ctrl.value
    assert "00:00, Old" not in host.content_ctrl.value
    assert host.content_ctrl.selection == (1, 4)


def test_article_chapter_links_resolve_relative_links_and_require_safe_http_urls():
    article = _article(
        chapters=[
            {"start": 0, "title": "Relative", "href": "/chapters/intro"},
            {"start": 10, "title": "Unsafe", "href": "javascript:alert(1)"},
            {"start": 20, "title": "No host", "href": "https:///missing-host"},
            {"start": 30, "title": "Credentials", "href": "https://user:secret@example.com/chapter"},
            {"start": 40, "title": "Whitespace", "href": "https://example.com/bad path"},
            {"start": 50, "title": "Control", "href": "https://example.com/bad\npath"},
            {"start": 60, "title": "Backslash", "href": r"https://example.com\@evil.test/chapter"},
            {"start": 70, "title": "Invalid port", "href": "https://example.com:not-a-port/chapter"},
        ]
    )
    host = _ChapterHost(article, _Player())

    links = host._article_chapter_links(article)

    assert links == [
        (
            article.chapters[0],
            "https://example.com/chapters/intro",
        )
    ]


def test_open_chapter_link_uses_browser_for_http_only(monkeypatch):
    article = _article()
    host = _ChapterHost(article, _Player())
    opened = []
    monkeypatch.setattr(mainframe.webbrowser, "open", opened.append)

    host.on_open_chapter_link("https://example.com/chapter")
    host.on_open_chapter_link("javascript:alert(1)")
    host.on_open_chapter_link("https://user@example.com/chapter")
    host.on_open_chapter_link("https://example.com:invalid/chapter")

    assert opened == ["https://example.com/chapter"]


def test_delayed_chapters_do_not_replace_newer_players_chapters():
    article = _article("old")
    player = _Player(
        current_article_id="new",
        current_chapters=[{"start": 0.0, "title": "New item"}],
    )
    host = _ChapterHost(article, player)
    chapters = [{"start": 0.0, "title": "Old item"}]

    host._apply_chapters_for_player(article.id, chapters, article.media_url)

    assert article.chapters == chapters
    assert player.updated == []
    assert player.current_chapters == [{"start": 0.0, "title": "New item"}]


def test_delayed_chapters_update_the_matching_player():
    article = _article()
    player = _Player(current_article_id=article.id)
    host = _ChapterHost(article, player)
    chapters = [{"start": 0.0, "title": "Intro"}]

    host._apply_chapters_for_player(article.id, chapters, article.media_url)

    assert player.updated == [chapters]


def test_opening_chapterless_article_clears_previous_player_chapters():
    article = _article()
    player = _Player(current_article_id="previous", current_chapters=[{"start": 0.0, "title": "Stale"}])
    host = _ChapterHost(article, player)

    host._open_article(article)

    assert player.updated == [[]]
    assert player.loaded[0][2] == []


def test_reopening_current_article_hands_new_chapters_to_player_before_toggle():
    chapters = [{"start": 0.0, "title": "Intro"}]
    article = _article(chapters=chapters)
    player = _Player(current_article_id=article.id, same_media=True)
    host = _ChapterHost(article, player)

    host._open_article(article)

    assert player.updated == [chapters]
    assert player.paused == 1
    assert player.loaded == []
