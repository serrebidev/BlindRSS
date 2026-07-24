# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

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


def test_feed_errors_dialog_controls_named(parent):
    errors = [
        {
            "id": "f1",
            "title": "Broken Feed",
            "url": "https://example.com/feed",
            "category": "Tech",
            "last_error": "HTTP 404: Not Found",
            "last_error_at": 1000.0,
            "last_success_at": None,
            "consecutive_failures": 3,
        }
    ]
    dlg = dialogs.FeedErrorsDialog(parent, errors)
    try:
        # Screen-reader names for the list and detail field.
        assert dlg.list.GetName() == "Feeds with errors"
        assert dlg.detail.GetName() == "Error details"
        # One row was populated with the feed name.
        assert dlg.list.GetItemCount() == 1
        assert dlg.list.GetItemText(0, 0) == "Broken Feed"
        assert dlg.list.GetItemText(0, 2) == "3"
        assert "404" in dlg.list.GetItemText(0, 3)
        # Detail text carries the full context needed to act on the feed.
        detail = dlg._build_detail_text(errors[0])
        assert "Broken Feed" in detail
        assert "https://example.com/feed" in detail
        assert "HTTP 404: Not Found" in detail
        assert "consecutive" in detail
    finally:
        dlg.Destroy()


def test_feed_errors_dialog_empty_state(parent):
    dlg = dialogs.FeedErrorsDialog(parent, [])
    try:
        assert dlg.list.GetItemCount() == 0
        assert "No feeds" in dlg.heading.GetLabel()
        # Action buttons are disabled when there is nothing to act on.
        assert not dlg.refresh_btn.IsEnabled()
        assert not dlg.remove_btn.IsEnabled()
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
        assert dlg.sort_choice.GetName() == "Sort results"
        # Sort combo defaults to Relevance (the default relevance ordering).
        assert dlg.sort_choice.GetSelection() == 0
        assert dlg.sort_choice.GetCount() == 4
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
        # Paths and credentials that are otherwise ambiguous when focused.
        assert dlg.dl_path_ctrl.GetName() == "Download path"
        assert dlg.ytdlp_cookies_ctrl.GetName() == "yt-dlp cookies file path"
        assert dlg.youtube_play_cache_dir_ctrl.GetName() == "YouTube playback cache folder"
        # wxOSX returns page labels with the mnemonic escape collapsed
        # ("Feeds & Articles"), wxMSW keeps the literal "&&"; normalize so the
        # assertion is about the words, not the platform's ampersand handling.
        page_labels = [
            dlg.notebook.GetPageText(index).replace("&&", "&")
            for index in range(dlg.notebook.GetPageCount())
        ]
        # Thin tabs (Downloads, Startup & Tray, Sounds, Announcements,
        # Groups.io) are labelled groups on the page they belong to now, not
        # tabs of their own; the surviving tabs kept their relative order.
        assert page_labels[:5] == [
            "General",
            "Feeds & Articles",
            "YouTube",
            "Media Player",
            "Provider",
        ]
        # Controls inside an absorbed tab's group sit on a nested panel, so ask
        # which page a control lives on rather than who its parent is.
        pages = {dlg.notebook.GetPage(i): i for i in range(dlg.notebook.GetPageCount())}

        def page_of(ctrl):
            window = ctrl
            while window is not None:
                if window in pages:
                    return pages[window]
                window = window.GetParent()
            return None

        assert page_of(dlg.refresh_ctrl) == page_labels.index("Feeds & Articles")
        assert page_of(dlg.automatic_refresh_workload_ctrl) == page_labels.index("Feeds & Articles")
        assert dlg.automatic_refresh_workload_ctrl.GetName() == "Local RSS automatic feed refresh workload"
        selected_workload = dlg.automatic_refresh_workload_map.get(
            dlg.automatic_refresh_workload_ctrl.GetStringSelection()
        )
        settings = dlg.get_data()
        assert settings["automatic_feed_refresh_workload"] == selected_workload
        assert settings["ignore_feed_cache"] is (selected_workload == "always_full")
        assert page_of(dlg.dl_path_ctrl) == page_labels.index("Media Player")
        assert page_of(dlg.start_in_tray_chk) == page_labels.index("General")
        assert page_of(dlg.ytdlp_cookies_ctrl) == page_labels.index("YouTube")
        assert page_of(dlg.install_updates_automatically_chk) == page_labels.index("Advanced")
        assert (
            dlg.install_updates_automatically_chk.GetLabel()
            == "Automatically install updates without confirmation"
        )

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
        # Notebook pages build on first view, so a test inspecting a page's
        # controls has to realise them first (get_data does the same).
        dlg._ensure_all_pages_built()
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


# --- Article list columns (article list columns) ---------------------------------------


def test_column_layout_panel_is_named_and_reorders(parent):
    """The column editor is driven entirely by keyboard: the CheckListBox is the
    order AND the visibility, so it must be named, and Move up/down must move
    the selected column while keeping it selected (NVDA announces the new spot)."""
    from core import article_columns

    panel = dialogs.ColumnLayoutPanel(parent, layout=None)
    try:
        assert panel.list_box.GetName() == "Article list columns"
        assert panel.get_layout() is not None

        # Select "author" (index 1 in the default layout) and move it down.
        panel.list_box.SetSelection(1)
        assert panel._selected_key() == "author"
        panel._move(1)

        keys = [e["key"] for e in panel.get_layout()]
        assert keys[1] != "author"
        # Focus follows the moved column, not the index it vacated.
        assert panel._selected_key() == "author"
        # Title stays pinned first no matter what.
        assert keys[0] == article_columns.PINNED_KEY
    finally:
        panel.Destroy()


def test_takeout_selection_uses_named_native_checkboxes(parent):
    dlg = dialogs.TakeoutImportSelectionDialog(
        parent,
        ["Subscribed channels (12)", "Playlists (3)"],
    )
    try:
        assert isinstance(dlg.items, dialogs.CheckListCtrl)
        assert dlg.items.GetName() == "YouTube Takeout items to import"
        assert dlg.GetSelections() == [0, 1]

        # This is the same state exposed through the native Windows ListView
        # accessibility object and announced by NVDA when Space toggles it.
        dlg.items.Check(1, False)
        assert dlg.GetSelections() == [0]
    finally:
        dlg.Destroy()


def test_column_layout_panel_inherit_mode_disables_editing(parent):
    """The per-feed tab's 'use global' checkbox must return None (inherit) and
    grey out the editor, so a feed cannot silently freeze today's global layout."""
    panel = dialogs.ColumnLayoutPanel(parent, layout=None, allow_inherit=True)
    try:
        assert panel.inherit_ctrl is not None
        assert panel.inherit_ctrl.GetValue() is True
        assert panel.get_layout() is None
        assert not panel.list_box.IsEnabled()
        assert not panel.up_btn.IsEnabled()

        panel.inherit_ctrl.SetValue(False)
        panel._sync_enabled()
        assert panel.list_box.IsEnabled()
        assert panel.get_layout() is not None
    finally:
        panel.Destroy()


def test_feed_properties_dialog_has_a_columns_tab(parent):
    class _Feed:
        id = "feed-1"
        title = "Example"
        url = "https://example.com/feed"
        category = "News"

    dlg = dialogs.FeedPropertiesDialog(parent, _Feed(), ["News", "Uncategorized"])
    try:
        labels = [dlg.notebook.GetPageText(i) for i in range(dlg.notebook.GetPageCount())]
        assert labels == ["General", "List Headers"]
        # Defaults to inheriting the global layout.
        assert dlg.columns_panel.get_layout() is None
        # The General fields still work after the notebook refactor.
        assert dlg.title_ctrl.GetName() == "Feed title"
    finally:
        dlg.Destroy()
