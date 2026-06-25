"""Accessibility (VoiceOver / screen-reader) checks for gui.dialogs.

The primary user is a blind VoiceOver user on macOS. On macOS wx maps to
NSAccessibility and ``widget.SetName(...)`` is what VoiceOver announces when a
control receives focus. A ``wx.StaticText`` label placed next to a field is
frequently NOT linked to that field for VoiceOver, so ambiguous fields (URLs,
API keys, paths, search boxes) and same-looking "Browse..." buttons get an
explicit accessible name.

These tests construct the real dialogs headlessly and assert ``GetName()`` on
the controls we labelled. A real ``wx.App()`` works in this environment, but the
whole module skips cleanly if it cannot (e.g. a headless CI with no display) so
it never hard-fails there.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

wx = pytest.importorskip("wx")

import gui.dialogs as dialogs  # noqa: E402
from core.config import ConfigManager  # noqa: E402


@pytest.fixture(scope="module")
def wx_app():
    """A module-scoped wx.App, skipping the whole module if it can't start."""
    try:
        app = wx.App()
    except Exception as exc:  # pragma: no cover - depends on display availability
        pytest.skip(f"no display / wx.App() unavailable: {exc}")
    yield app
    # Let wx tear down naturally; explicit destroy can crash some backends.


@pytest.fixture
def parent(wx_app):
    """A throwaway top-level frame to host each dialog."""
    frame = wx.Frame(None)
    yield frame
    try:
        frame.Destroy()
    except Exception:
        pass


def _names(*ctrls):
    return [c.GetName() for c in ctrls]


def test_add_feed_dialog_fields_named(parent):
    dlg = dialogs.AddFeedDialog(parent, categories=["Uncategorized", "YouTube"])
    try:
        assert dlg.url_ctrl.GetName() == "Feed or Media URL"
        assert dlg.cat_ctrl.GetName() == "Category"
    finally:
        dlg.Destroy()


def test_feed_properties_dialog_fields_named(parent):
    class _Feed:
        title = "Example"
        url = "https://example.com/feed"
        category = "News"

    dlg = dialogs.FeedPropertiesDialog(parent, _Feed(), ["News", "Uncategorized"])
    try:
        assert dlg.title_ctrl.GetName() == "Feed title"
        assert dlg.url_ctrl.GetName() == "Feed URL"
        assert dlg.cat_ctrl.GetName() == "Category"
    finally:
        dlg.Destroy()


def test_exclude_notification_feeds_list_named(parent):
    dlg = dialogs.ExcludeNotificationFeedsDialog(
        parent,
        feed_entries=[("1", "Feed One"), ("2", "Feed Two")],
        excluded_ids=["2"],
    )
    try:
        assert dlg.feed_list.GetName() == "Feeds (checked feeds send notifications)"
    finally:
        dlg.Destroy()


def test_feed_search_dialog_controls_named(parent):
    dlg = dialogs.FeedSearchDialog(parent)
    try:
        assert dlg.search_ctrl.GetName() == "Search for a podcast or RSS feed"
        assert dlg.source_combo.GetName() == "Search source"
        assert dlg.results_list.GetName() == "Search results"
    finally:
        dlg._stop_event.set()
        dlg.Destroy()


def test_ytdlp_global_search_dialog_controls_named(parent):
    dlg = dialogs.YtdlpGlobalSearchDialog(parent)
    try:
        assert dlg.search_ctrl.GetName() == "Video search"
        assert dlg.scope_choice.GetName() == "Search sites"
        assert dlg.filter_choice.GetName() == "Filter results by site"
        # Pre-existing label that must not regress.
        assert dlg.results_list.GetName() == "Search results"
    finally:
        dlg._stop_event.set()
        dlg.Destroy()


def test_persistent_search_dialog_list_named(parent):
    dlg = dialogs.PersistentSearchDialog(parent, searches=["python", "wxpython"])
    try:
        assert dlg.list_ctrl.GetName() == "Saved searches"
    finally:
        dlg.Destroy()


def test_settings_dialog_field_names(parent):
    config = ConfigManager().config
    try:
        dlg = dialogs.SettingsDialog(parent, config, notification_feeds=[])
    except TypeError:
        dlg = dialogs.SettingsDialog(parent, config)
    try:
        # General tab: paths and credentials that are otherwise ambiguous when focused.
        assert dlg.dl_path_ctrl.GetName() == "Download path"
        assert dlg.ytdlp_cookies_ctrl.GetName() == "yt-dlp cookies file path"
        assert dlg.youtube_play_cache_dir_ctrl.GetName() == "YouTube playback cache folder"

        # Media tools overrides (pre-existing names that must not regress).
        assert (
            dlg._media_tool_path_ctrls["custom_ffmpeg_path"].GetName()
            == "FFmpeg executable path override"
        )
        assert (
            dlg._media_tool_path_ctrls["custom_ffprobe_path"].GetName()
            == "FFprobe executable path override"
        )
        assert (
            dlg._media_tool_path_ctrls["custom_ytdlp_path"].GetName()
            == "yt-dlp executable path override"
        )

        # Sounds tab: each path field named after its label.
        assert dlg.sound_complete_ctrl.GetName() == "Refresh Complete Sound"
        assert dlg.sound_error_ctrl.GetName() == "Refresh Error Sound"

        # Translate tab: target language + every provider's API key field
        # (password-masked, so visually empty when focused).
        assert dlg.translation_target_language_ctrl.GetName() == "Target language"
        assert dlg.translation_grok_api_key_ctrl.GetName() == "Grok (xAI) API key"
        assert dlg.translation_groq_api_key_ctrl.GetName() == "Groq API key"
        assert dlg.translation_openai_api_key_ctrl.GetName() == "OpenAI API key"
        assert dlg.translation_openrouter_api_key_ctrl.GetName() == "OpenRouter API key"
        assert dlg.translation_gemini_api_key_ctrl.GetName() == "Gemini API key"
        assert dlg.translation_qwen_api_key_ctrl.GetName() == "Qwen API key"
    finally:
        dlg.Destroy()


def test_settings_dialog_provider_credential_fields_named(parent):
    """Provider auth fields live in a FlexGridSizer whose StaticText label is not
    linked to the field for VoiceOver, so each field carries its own name."""
    config = ConfigManager().config
    try:
        dlg = dialogs.SettingsDialog(parent, config, notification_feeds=[])
    except TypeError:
        dlg = dialogs.SettingsDialog(parent, config)
    try:
        panels = getattr(dlg, "_provider_panels", {})

        miniflux_ctrls = panels.get("miniflux", (None, {}))[1]
        assert miniflux_ctrls["url"].GetName() == "Miniflux URL"
        assert miniflux_ctrls["api_key"].GetName() == "Miniflux API Key"

        bazqux_ctrls = panels.get("bazqux", (None, {}))[1]
        assert bazqux_ctrls["email"].GetName() == "BazQux Email"
        assert bazqux_ctrls["password"].GetName() == "BazQux Password"

        # Inoreader fields are built by a dedicated helper.
        assert dlg._inoreader_app_id_ctrl.GetName() == "Inoreader App ID"
        assert dlg._inoreader_app_key_ctrl.GetName() == "Inoreader App Key"
        assert dlg._inoreader_redirect_uri_ctrl.GetName() == "Redirect URI"
    finally:
        dlg.Destroy()
