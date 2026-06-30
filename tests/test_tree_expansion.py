"""Default collapse/expand state of the feed category tree (issue #33).

The tree is rebuilt on every refresh, so the app must (a) apply the configured
default expansion state and (b) preserve the user's manual expand/collapse
choices across rebuilds rather than re-expanding everything. These tests cover
the pure decision logic, the config default, and the Settings round-trip.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import DEFAULT_CONFIG  # noqa: E402


def test_config_default_is_expanded_for_backward_compat():
    # Legacy behavior (fully expanded) must remain the out-of-the-box default.
    assert DEFAULT_CONFIG.get("category_tree_default_expanded") is True


wx = pytest.importorskip("wx")

import gui.mainframe as mainframe  # noqa: E402
import gui.dialogs as dialogs  # noqa: E402
from core.config import ConfigManager  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


def test_untouched_category_follows_default():
    resolve = mainframe.MainFrame._resolve_category_expanded
    assert resolve("Tech", set(), set(), True) is True
    assert resolve("Tech", set(), set(), False) is False


def test_manual_choice_overrides_default():
    resolve = mainframe.MainFrame._resolve_category_expanded
    # User collapsed it -> stays collapsed even when the default is "expanded".
    assert resolve("Tech", set(), {"Tech"}, True) is False
    # User expanded it -> stays expanded even when the default is "collapsed".
    assert resolve("Tech", {"Tech"}, set(), False) is True


def test_settings_dialog_tree_state_named_and_roundtrips(wx_app):
    frame = wx.Frame(None)
    try:
        config = dict(ConfigManager().config)
        config["category_tree_default_expanded"] = False
        try:
            dlg = dialogs.SettingsDialog(frame, config, notification_feeds=[])
        except TypeError:
            dlg = dialogs.SettingsDialog(frame, config)
        try:
            # Accessible name + the saved "collapsed" value is reflected on load.
            assert dlg.tree_expand_ctrl.GetName() == "Feed category tree default state on startup"
            assert dlg.tree_expand_ctrl.GetStringSelection() == "All items collapsed"
            # Changing the choice round-trips through get_data().
            dlg.tree_expand_ctrl.SetStringSelection("All items expanded")
            assert dlg.get_data()["category_tree_default_expanded"] is True
        finally:
            dlg.Destroy()
    finally:
        frame.Destroy()
