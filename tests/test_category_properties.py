# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Category Properties: rename and re-parent a category (issue #86).

The GUI half of the feature, in two layers. The dispatch tests swap
CategoryPropertiesDialog for a stub that returns whatever the test wants the
user to have entered, following the stand-in-host pattern used by
test_status_bar_activity.py and test_category_opml_export.py. The section at the
bottom builds the real wx dialog, because a dialog that raises on construction
fails silently in the app and looks exactly like a dead shortcut.
"""

import os
import sys
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import gui.mainframe as mainframe


class _Provider:
    def __init__(self, categories, supports_sub=True, uncategorized_real=False):
        self._categories = list(categories)
        self._supports_sub = supports_sub
        self._uncategorized_real = uncategorized_real
        self.moves = []
        self.renames = []
        self.move_result = True
        self.rename_result = True

    def get_categories(self):
        return list(self._categories)

    def supports_subcategories(self):
        return self._supports_sub

    def uncategorized_is_real_category(self):
        return self._uncategorized_real

    def move_category(self, title, parent_title=None):
        self.moves.append((title, parent_title))
        return self.move_result

    def rename_category(self, old_title, new_title):
        self.renames.append((old_title, new_title))
        return self.rename_result


class _Host:
    _eligible_parent_categories = mainframe.MainFrame._eligible_parent_categories
    _is_protected_uncategorized = mainframe.MainFrame._is_protected_uncategorized
    on_edit_category = mainframe.MainFrame.on_edit_category
    _cmd_edit_selected = mainframe.MainFrame._cmd_edit_selected

    def __init__(self, provider):
        self.provider = provider
        self.refresh_calls = 0
        self.edit_feed_calls = 0

    def refresh_feeds(self):
        self.refresh_calls += 1

    def on_edit_feed(self, _event=None):
        self.edit_feed_calls += 1


class _StubDialog:
    """Stands in for CategoryPropertiesDialog; records how it was constructed."""

    instances = []

    result = None  # (return code, (name, parent))

    def __init__(self, parent, category_path, parent_identities, current_parent=None, allow_parent_edit=True):
        self.category_path = category_path
        self.parent_identities = list(parent_identities)
        self.current_parent = current_parent
        self.allow_parent_edit = allow_parent_edit
        self.destroyed = False
        _StubDialog.instances.append(self)

    def ShowModal(self):
        return _StubDialog.result[0]

    def get_data(self):
        return _StubDialog.result[1]

    def Destroy(self):
        self.destroyed = True


def _patch(monkeypatch, code, data):
    _StubDialog.instances = []
    _StubDialog.result = (code, data)
    monkeypatch.setattr(mainframe, "CategoryPropertiesDialog", _StubDialog)
    messages = []
    monkeypatch.setattr(mainframe.wx, "MessageBox", lambda *a, **k: messages.append(a))
    return messages


def _host(monkeypatch, code=None, data=None, categories=("Work", "Tech", "Tech / Phones"),
          supports_sub=True, uncategorized_real=False):
    if code is None:
        code = mainframe.wx.ID_OK
    messages = _patch(monkeypatch, code, data or ("Tech", None))
    provider = _Provider(categories, supports_sub=supports_sub, uncategorized_real=uncategorized_real)
    return _Host(provider), messages


# --- the parent picker's candidate list ------------------------------------


def test_eligible_parents_exclude_the_category_and_its_own_subtree(monkeypatch):
    host, _ = _host(monkeypatch, categories=["Work", "Tech", "Tech / Phones", "Tech / Phones / Android"])

    assert host._eligible_parent_categories("Tech") == ["Work"]


def test_eligible_parents_exclude_uncategorized(monkeypatch):
    host, _ = _host(monkeypatch, categories=["Uncategorized", "Work"])

    assert host._eligible_parent_categories("Tech") == ["Work"]


def test_eligible_parents_keep_a_sibling_whose_name_merely_starts_the_same(monkeypatch):
    """'Technology' is not inside 'Tech' -- only a real path prefix is."""
    host, _ = _host(monkeypatch, categories=["Technology", "Tech / Phones"])

    assert host._eligible_parent_categories("Tech") == ["Technology"]


# --- rename / move dispatch -------------------------------------------------


def test_moving_a_category_calls_the_provider_and_reloads(monkeypatch):
    host, _ = _host(monkeypatch, data=("Tech", "Work"))

    host.on_edit_category("Tech")

    assert host.provider.moves == [("Tech", "Work")]
    assert host.provider.renames == []
    assert host.refresh_calls == 1


def test_renaming_a_category_calls_the_provider_with_the_new_leaf(monkeypatch):
    host, _ = _host(monkeypatch, data=("Gadgets", None))

    host.on_edit_category("Tech")

    assert host.provider.renames == [("Tech", "Gadgets")]
    assert host.provider.moves == []
    assert host.refresh_calls == 1


def test_renaming_and_moving_together_moves_first_then_renames_the_moved_path(monkeypatch):
    """The rename has to target the path the move produced, not the old one."""
    host, _ = _host(monkeypatch, data=("Gadgets", "Work"))

    host.on_edit_category("Tech")

    assert host.provider.moves == [("Tech", "Work")]
    assert host.provider.renames == [("Work / Tech", "Gadgets")]
    assert host.refresh_calls == 1


def test_no_change_touches_nothing(monkeypatch):
    host, _ = _host(monkeypatch, data=("Phones", "Tech"))

    host.on_edit_category("Tech / Phones")

    assert host.provider.moves == []
    assert host.provider.renames == []
    assert host.refresh_calls == 0


def test_cancel_touches_nothing(monkeypatch):
    host, _ = _host(monkeypatch, code=mainframe.wx.ID_CANCEL, data=("Gadgets", "Work"))

    host.on_edit_category("Tech")

    assert host.provider.moves == []
    assert host.provider.renames == []
    assert host.refresh_calls == 0
    assert _StubDialog.instances[0].destroyed is True


def test_blank_name_keeps_the_current_one(monkeypatch):
    host, _ = _host(monkeypatch, data=("", None))

    host.on_edit_category("Tech")

    assert host.provider.renames == []
    assert host.provider.moves == []


# --- Uncategorized: virtual (protected) vs real (Miniflux) ------------------


def test_uncategorized_is_protected_by_default(monkeypatch):
    host, _ = _host(monkeypatch)
    assert host._is_protected_uncategorized("Uncategorized") is True
    # A blank path is "no category" too.
    assert host._is_protected_uncategorized("") is True
    # A normal category is never protected.
    assert host._is_protected_uncategorized("Tech") is False


def test_uncategorized_is_not_protected_when_the_provider_says_it_is_real(monkeypatch):
    host, _ = _host(monkeypatch, uncategorized_real=True)
    assert host._is_protected_uncategorized("Uncategorized") is False


def test_editing_a_real_uncategorized_opens_the_dialog_and_renames(monkeypatch):
    """On Miniflux, Uncategorized is a real category: F2/Edit should work, and
    with no parent picker (flat provider) it renames like any other."""
    host, _ = _host(
        monkeypatch, data=("Archive", None),
        supports_sub=False, uncategorized_real=True,
    )

    host.on_edit_category("Uncategorized")

    assert _StubDialog.instances and _StubDialog.instances[0].category_path == "Uncategorized"
    assert host.provider.renames == [("Uncategorized", "Archive")]


def test_f2_on_a_real_uncategorized_opens_properties(monkeypatch):
    host, _ = _host(monkeypatch, code=mainframe.wx.ID_CANCEL, uncategorized_real=True)
    host.tree = _Tree({"type": "category", "id": "Uncategorized"})

    host._cmd_edit_selected(None)

    assert _StubDialog.instances and _StubDialog.instances[0].category_path == "Uncategorized"


def test_uncategorized_says_why_it_cannot_be_edited(monkeypatch):
    """Uncategorized has no row to rename and no parent to move. Silence here
    reads as a broken shortcut -- with a screen reader there is no other signal."""
    host, messages = _host(monkeypatch, data=("Anything", "Work"))

    host.on_edit_category("Uncategorized")

    assert _StubDialog.instances == []
    assert messages and "cannot be renamed or moved" in messages[0][0]


def test_a_blank_category_path_counts_as_uncategorized(monkeypatch):
    """"No category" and "Uncategorized" are the same thing (is_uncategorized("")
    is True), so a blank path takes the same explain-and-stop path."""
    host, messages = _host(monkeypatch, data=("Anything", "Work"))

    host.on_edit_category("")

    assert _StubDialog.instances == []
    assert messages and "cannot be renamed or moved" in messages[0][0]


def test_a_failed_move_reports_and_does_not_rename(monkeypatch):
    host, messages = _host(monkeypatch, data=("Gadgets", "Work"))
    host.provider.move_result = False

    host.on_edit_category("Tech")

    assert host.provider.renames == []
    assert host.refresh_calls == 0
    assert messages and "Could not move category." in messages[0][0]


def test_a_failed_rename_after_a_good_move_still_shows_the_move(monkeypatch):
    host, messages = _host(monkeypatch, data=("Gadgets", "Work"))
    host.provider.rename_result = False

    host.on_edit_category("Tech")

    assert host.provider.moves == [("Tech", "Work")]
    assert host.refresh_calls == 1
    assert messages and "Could not rename category." in messages[0][0]


# --- flat providers ---------------------------------------------------------


def test_flat_provider_gets_no_parent_picker_and_never_moves(monkeypatch):
    host, _ = _host(monkeypatch, data=("Gadgets", "Work"), supports_sub=False)

    host.on_edit_category("Tech")

    dialog = _StubDialog.instances[0]
    assert dialog.allow_parent_edit is False
    assert dialog.parent_identities == []
    # Even if the stub reports a parent, a flat provider is never asked to move.
    assert host.provider.moves == []
    assert host.provider.renames == [("Tech", "Gadgets")]


# --- the dialog is opened with the category's current parent preselected ----


def test_dialog_is_seeded_with_the_current_parent_and_candidates(monkeypatch):
    host, _ = _host(monkeypatch, code=mainframe.wx.ID_CANCEL, categories=["Work", "Tech", "Tech / Phones"])

    host.on_edit_category("Tech / Phones")

    dialog = _StubDialog.instances[0]
    assert dialog.category_path == "Tech / Phones"
    assert dialog.current_parent == "Tech"
    assert dialog.parent_identities == ["Tech", "Work"]


# --- F2 routing -------------------------------------------------------------


class _Tree:
    def __init__(self, data):
        self._data = data

    def GetSelection(self):
        return SimpleNamespace(IsOk=lambda: True)

    def GetItemData(self, _item):
        return self._data


def test_f2_on_a_category_opens_category_properties(monkeypatch):
    host, _ = _host(monkeypatch, code=mainframe.wx.ID_CANCEL)
    host.tree = _Tree({"type": "category", "id": "Tech"})

    host._cmd_edit_selected(None)

    assert _StubDialog.instances[0].category_path == "Tech"
    assert host.edit_feed_calls == 0


def test_f2_on_a_feed_still_opens_feed_properties(monkeypatch):
    host, _ = _host(monkeypatch, code=mainframe.wx.ID_CANCEL)
    host.tree = _Tree({"type": "feed", "id": "feed-1"})

    host._cmd_edit_selected(None)

    assert _StubDialog.instances == []
    assert host.edit_feed_calls == 1


def test_f2_on_uncategorized_explains_instead_of_doing_nothing(monkeypatch):
    host, messages = _host(monkeypatch, code=mainframe.wx.ID_CANCEL)
    host.tree = _Tree({"type": "category", "id": "Uncategorized"})

    host._cmd_edit_selected(None)

    assert _StubDialog.instances == []
    assert host.edit_feed_calls == 0
    assert messages and "cannot be renamed or moved" in messages[0][0]


# --- the real wx dialog -----------------------------------------------------
#
# Everything above stubs the dialog. These build the real one: a dialog that
# raises on construction fails silently in the app (the handler's caller logs
# and moves on), which is exactly how the first attempt at this feature shipped
# looking like "nothing happened".


import pytest

wx = pytest.importorskip("wx")

from gui.dialogs import CategoryPropertiesDialog


@pytest.fixture
def wxapp():
    app = wx.App(False)
    yield app
    try:
        app.Destroy()
    except Exception:
        pass


def test_real_dialog_with_a_parent_picker_reports_name_and_parent(wxapp):
    frame = wx.Frame(None)
    try:
        dlg = CategoryPropertiesDialog(
            frame, "Work / Tech", ["Work", "Personal"], current_parent="Work"
        )
        try:
            assert dlg.name_ctrl.GetValue() == "Tech"
            assert dlg.parent_ctrl is not None
            # Index 0 is "(None - Top Level)", so the current parent is at 1.
            assert dlg.parent_ctrl.GetSelection() == 1
            assert dlg.get_data() == ("Tech", "Work")

            dlg.parent_ctrl.SetSelection(0)
            assert dlg.get_data() == ("Tech", None)
        finally:
            dlg.Destroy()
    finally:
        frame.Destroy()


def test_real_dialog_on_a_flat_provider_has_no_picker_and_still_returns_a_name(wxapp):
    frame = wx.Frame(None)
    try:
        dlg = CategoryPropertiesDialog(frame, "News", [], allow_parent_edit=False)
        try:
            assert dlg.parent_ctrl is None
            dlg.name_ctrl.SetValue("Headlines")
            # get_data() must not raise with no picker present.
            assert dlg.get_data() == ("Headlines", None)
        finally:
            dlg.Destroy()
    finally:
        frame.Destroy()


def test_real_dialog_survives_a_top_level_category_and_an_empty_candidate_list(wxapp):
    frame = wx.Frame(None)
    try:
        dlg = CategoryPropertiesDialog(frame, "Tech", [], current_parent=None)
        try:
            assert dlg.name_ctrl.GetValue() == "Tech"
            assert dlg.parent_ctrl.GetSelection() == 0
            assert dlg.get_data() == ("Tech", None)
        finally:
            dlg.Destroy()
    finally:
        frame.Destroy()
