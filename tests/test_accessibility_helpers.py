from types import SimpleNamespace

from gui.accessibility import (
    build_accessible_view_entries,
    format_accessible_view_label,
    visible_accessible_view_entries,
    voiceover_is_running,
)


def test_build_accessible_view_entries_flattens_specials_categories_and_feeds():
    feeds = [
        SimpleNamespace(id="feed-news", title="Daily News", category="News", unread_count=3),
        SimpleNamespace(id="feed-tech", title="Tech Talk", category="Tech", unread_count=0),
    ]

    entries = build_accessible_view_entries(
        feeds,
        categories=["News", "Tech"],
        hierarchy={"Tech": "News"},
        include_favorites=True,
    )

    labels = [entry["label"] for entry in entries]
    view_ids = [entry["view_id"] for entry in entries]

    assert labels[:4] == ["All Articles", "Unread Articles", "Read Articles", "Favorites"]
    assert "Category: News" in labels
    assert "Category: News > Tech" in labels
    assert "Feed: Daily News, 3 unread (News)" in labels
    assert "Feed: Tech Talk (News > Tech)" in labels
    assert view_ids[:4] == ["all", "unread:all", "read:all", "favorites:all"]
    assert "category:News" in view_ids
    assert "category:Tech" in view_ids
    assert "feed-news" in view_ids
    assert "feed-tech" in view_ids


def test_build_accessible_view_entries_adds_uncategorized_when_needed():
    feeds = [
        SimpleNamespace(id="feed-1", title="Loose Feed", category="", unread_count=0),
    ]

    entries = build_accessible_view_entries(feeds, categories=[], hierarchy={}, include_favorites=False)
    labels = [entry["label"] for entry in entries]

    assert "Category: Uncategorized" in labels
    assert "Feed: Loose Feed (Uncategorized)" in labels


def test_visible_accessible_view_entries_hide_children_of_collapsed_categories():
    feeds = [
        SimpleNamespace(id="feed-news", title="Daily News", category="News", unread_count=3),
        SimpleNamespace(id="feed-tech", title="Tech Talk", category="Tech", unread_count=0),
    ]

    entries = build_accessible_view_entries(
        feeds,
        categories=["News", "Tech"],
        hierarchy={"Tech": "News"},
        include_favorites=False,
    )

    visible = visible_accessible_view_entries(entries, expanded_categories={"News"})
    labels = [entry["label"] for entry in visible]

    assert "Category: News" in labels
    assert "Feed: Daily News, 3 unread (News)" in labels
    assert "Category: News > Tech" in labels
    assert "Feed: Tech Talk (News > Tech)" not in labels


def test_format_accessible_view_label_adds_state_and_indentation():
    category_entry = {
        "label": "Category: News > Tech",
        "kind": "category",
        "parent_cats": ["News"],
        "cat_name": "Tech",
    }
    feed_entry = {
        "label": "Feed: Tech Talk (News > Tech)",
        "kind": "feed",
        "parent_cats": ["News", "Tech"],
    }

    assert (
        format_accessible_view_label(category_entry, expanded_categories={"News", "Tech"})
        == "  Category: News > Tech, expanded"
    )
    assert format_accessible_view_label(category_entry, expanded_categories={"News"}) == "  Category: News > Tech, collapsed"
    assert format_accessible_view_label(feed_entry, expanded_categories={"News", "Tech"}) == "    Feed: Tech Talk (News > Tech)"


def test_voiceover_is_running_true_when_pgrep_finds_process(monkeypatch):
    class Result:
        returncode = 0
        stdout = "123\n"

    monkeypatch.setattr("gui.accessibility.subprocess.run", lambda *args, **kwargs: Result())
    assert voiceover_is_running() is True


def test_voiceover_is_running_false_when_pgrep_fails(monkeypatch):
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr("gui.accessibility.subprocess.run", lambda *args, **kwargs: Result())
    assert voiceover_is_running() is False
