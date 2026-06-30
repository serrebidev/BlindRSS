from types import SimpleNamespace

import gui.mainframe as mainframe


class _ListCtrl:
    def __init__(self):
        self.rows = []
        self.frozen = False

    def DeleteAllItems(self):
        self.rows = []

    def InsertItem(self, idx, text):
        row = [""] * 6
        row[mainframe.ARTICLE_COL_TITLE] = text
        self.rows.insert(idx, row)
        return idx

    def SetItem(self, idx, col, text):
        self.rows[idx][col] = text

    def Freeze(self):
        self.frozen = True

    def Thaw(self):
        self.frozen = False


class _Host:
    _render_articles_list = mainframe.MainFrame._render_articles_list
    _raw_article_description = mainframe.MainFrame._raw_article_description
    _article_description_text = mainframe.MainFrame._article_description_text
    _article_description_preview = mainframe.MainFrame._article_description_preview

    def __init__(self):
        self.list_ctrl = _ListCtrl()
        self.feed_map = {"f1": SimpleNamespace(title="Example Feed")}

    def _get_display_title(self, article):
        return article.title

    def _show_images_for_feed(self, _feed_id):
        return False

    def _strip_html(self, html, include_images=None):
        return mainframe.utils.html_to_text(html, include_images=bool(include_images))


def _article(**kw):
    data = dict(
        title="Title",
        url="https://example.com/article",
        content="<p>Full feed content.</p>",
        description="<p>Short <strong>RSS description</strong>.</p>",
        date="2026-05-31T00:00:00Z",
        author="Author",
        feed_id="f1",
        is_read=False,
    )
    data.update(kw)
    return SimpleNamespace(**data)


def test_article_list_renders_description_column_without_moving_status():
    host = _Host()

    host._render_articles_list([_article()])

    row = host.list_ctrl.rows[0]
    assert row[mainframe.ARTICLE_COL_DESCRIPTION] == "Short RSS description."
    assert row[mainframe.ARTICLE_COL_STATUS] == "Unread"


def test_description_preview_truncates_long_text():
    host = _Host()
    article = _article(description="<p>" + ("word " * 20) + "</p>")

    preview = host._article_description_preview(article, max_len=24)

    assert len(preview) <= 24
    assert preview.endswith("...")


def test_description_uses_content_only_when_description_is_legacy_none():
    host = _Host()
    article = _article(description=None, content="<p>Legacy content fallback.</p>")

    assert host._article_description_text(article) == "Legacy content fallback."
