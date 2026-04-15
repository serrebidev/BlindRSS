from types import SimpleNamespace

from gui.accessibility import build_accessible_view_entries, voiceover_is_running


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
