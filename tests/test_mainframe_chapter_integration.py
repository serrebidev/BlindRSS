from types import SimpleNamespace

import gui.mainframe as mainframe


class _ListCtrl:
    def __init__(self):
        self.labels = {}

    def SetItem(self, idx, column, label):
        self.labels[(int(idx), int(column))] = str(label)


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


def _article(article_id="article-1", chapters=None):
    return SimpleNamespace(
        id=article_id,
        cache_id=f"feed:{article_id}",
        title="Episode",
        chapters=list(chapters or []),
        media_url="https://example.com/audio.mp3",
        media_type="audio/mpeg",
        url="https://example.com/episode",
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
