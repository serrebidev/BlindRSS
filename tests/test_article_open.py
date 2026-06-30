"""Custom 'Article Opening Method' command parsing and the Settings UI (issue #31).

Users can open article links with a custom browser/command (e.g.
"chrome --incognito %1") instead of the OS default. These tests cover the pure
command parser, the not-found error path, the config defaults, and the Settings
round-trip.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import utils  # noqa: E402
from core.config import DEFAULT_CONFIG  # noqa: E402


def test_config_defaults_are_default_browser():
    assert DEFAULT_CONFIG.get("article_open_method") == "default"
    assert DEFAULT_CONFIG.get("article_open_command") == ""


def test_substitutes_placeholder_in_place():
    assert utils.build_open_command("chrome --incognito %1", "http://x/a") == [
        "chrome",
        "--incognito",
        "http://x/a",
    ]


def test_placeholder_inside_token_is_replaced():
    assert utils.build_open_command("open --url=%1", "http://x") == ["open", "--url=http://x"]


def test_url_appended_when_no_placeholder():
    assert utils.build_open_command("firefox", "http://x") == ["firefox", "http://x"]


def test_url_with_spaces_stays_single_argument():
    argv = utils.build_open_command("chrome %1", "http://x/a b c")
    assert argv == ["chrome", "http://x/a b c"]


def test_empty_template_raises():
    with pytest.raises(ValueError):
        utils.build_open_command("   ", "http://x")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows path quoting")
def test_quoted_windows_path_preserves_backslashes():
    template = r'"C:\Program Files\Mozilla Firefox\firefox.exe" --private-window %1'
    argv = utils.build_open_command(template, "http://x")
    assert argv == [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        "--private-window",
        "http://x",
    ]


def test_launch_reports_missing_executable():
    ok, err = utils.launch_open_command("definitely_not_a_real_program_xyz123 %1", "http://x")
    assert ok is False
    assert "not found" in err.lower()


def test_launch_reports_empty_command():
    ok, err = utils.launch_open_command("", "http://x")
    assert ok is False
    assert err


wx = pytest.importorskip("wx")

import gui.dialogs as dialogs  # noqa: E402
from core.config import ConfigManager  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app


def test_settings_dialog_article_open_controls(wx_app):
    frame = wx.Frame(None)
    try:
        config = dict(ConfigManager().config)
        config["article_open_method"] = "custom"
        config["article_open_command"] = "chrome --incognito %1"
        try:
            dlg = dialogs.SettingsDialog(frame, config, notification_feeds=[])
        except TypeError:
            dlg = dialogs.SettingsDialog(frame, config)
        try:
            # Accessible names.
            assert dlg.article_open_method_ctrl.GetName() == "Article opening method"
            assert dlg.article_open_command_ctrl.GetName() == "Custom article open command"
            # Loaded values reflect config; custom mode enables the command field.
            assert dlg.article_open_method_ctrl.GetStringSelection() == "Custom command"
            assert dlg.article_open_command_ctrl.GetValue() == "chrome --incognito %1"
            assert dlg.article_open_command_ctrl.IsEnabled()
            assert dlg.article_open_test_btn.IsEnabled()

            data = dlg.get_data()
            assert data["article_open_method"] == "custom"
            assert data["article_open_command"] == "chrome --incognito %1"

            # Switching to default browser disables the command field/Test button.
            dlg.article_open_method_ctrl.SetStringSelection("Default browser")
            dlg._sync_article_open_controls()
            assert not dlg.article_open_command_ctrl.IsEnabled()
            assert not dlg.article_open_test_btn.IsEnabled()
            assert dlg.get_data()["article_open_method"] == "default"
        finally:
            dlg.Destroy()
    finally:
        frame.Destroy()
