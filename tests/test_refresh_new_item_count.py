"""New-item counting across repeated per-feed refresh reports.

Miniflux reports a feed twice in one refresh: its pre-refresh counts when the
targeted refresh returns, then the fresh counts. Counting only the first report
made every manual Miniflux refresh find zero new items, so the "refresh
complete" sound (and new-article notifications) never fired.
"""

from gui.mainframe import MainFrame


def _extract(state, snapshot, counted):
    return MainFrame._extract_new_items(None, state, snapshot, counted)


def test_later_report_with_fresh_counts_is_counted():
    snapshot = {"7": 2}
    counted = {}
    assert _extract({"id": 7, "unread_count": 2, "new_items": None}, snapshot, counted) == 0
    assert _extract({"id": 7, "unread_count": 5, "new_items": None}, snapshot, counted) == 3


def test_repeated_report_is_not_counted_twice():
    snapshot = {"7": 2}
    counted = {}
    assert _extract({"id": "7", "unread_count": 5}, snapshot, counted) == 3
    assert _extract({"id": "7", "unread_count": 5}, snapshot, counted) == 0
    assert _extract({"id": "7", "unread_count": 6}, snapshot, counted) == 1


def test_explicit_new_items_counted_once():
    counted = {}
    assert _extract({"id": "a", "new_items": 4}, {}, counted) == 4
    assert _extract({"id": "a", "new_items": 4}, {}, counted) == 0
    assert _extract({"id": "b", "new_items": 0}, {}, counted) == 0
