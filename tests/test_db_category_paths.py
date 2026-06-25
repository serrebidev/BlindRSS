from core import db


def test_make_category_path_joins_parent_and_leaf():
    assert db.make_category_path("Podcasts", "Others") == "Podcasts / Others"
    assert db.make_category_path("", "Top Level") == "Top Level"
    assert db.make_category_path(None, "Top Level") == "Top Level"
    assert db.make_category_path("  Tech  ", "  News  ") == "Tech / News"


def test_make_category_path_supports_deep_paths():
    inner = db.make_category_path("A", "B")
    assert db.make_category_path(inner, "C") == "A / B / C"


def test_category_display_leaf_returns_last_segment():
    assert db.category_display_leaf("A / B / C") == "C"
    assert db.category_display_leaf("Top") == "Top"
    assert db.category_display_leaf("") == ""
    assert db.category_display_leaf(None) == ""


def test_sanitize_category_leaf_strips_separator():
    assert db.sanitize_category_leaf("News / World") == "News - World"
    assert db.sanitize_category_leaf("  Spaced  ") == "Spaced"
    assert db.sanitize_category_leaf(None) == ""


def test_category_path_round_trip_is_collision_safe():
    # Issue #27: a shared leaf name under different parents must keep distinct
    # path identities while still displaying the same leaf in the UI.
    a = db.make_category_path("Podcasts", db.sanitize_category_leaf("News"))
    b = db.make_category_path("Video", db.sanitize_category_leaf("News"))

    assert a != b
    assert db.category_display_leaf(a) == "News"
    assert db.category_display_leaf(b) == "News"
