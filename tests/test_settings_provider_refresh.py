# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression coverage for preserving the article list after Settings."""

import gui.mainframe as mainframe
from gui.mainframe import provider_configuration_changed


class _ConfigManager:
    def __init__(self):
        self.config = {
            "active_provider": "local",
            "providers": {"local": {}},
            "data_location": "app_folder",
        }

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value


class _NoOpSettingsDialog:
    def __init__(self, *_args, **_kwargs):
        self.destroyed = False

    def ShowModal(self):
        return mainframe.wx.ID_OK

    def get_data(self):
        return {
            "active_provider": "local",
            "providers": {"local": {}},
            "data_location": "app_folder",
        }

    def Destroy(self):
        self.destroyed = True


class _ArticleList:
    def __init__(self):
        self.clear_calls = 0

    def DeleteAllItems(self):
        self.clear_calls += 1


class _SettingsHost:
    on_settings = mainframe.MainFrame.on_settings

    def __init__(self):
        self.config_manager = _ConfigManager()
        self.list_ctrl = _ArticleList()
        self.content_ctrl = object()
        self.current_articles = [object()]

    def _collect_notification_feed_entries(self):
        return []

    def _normalize_search_mode(self, value):
        return value

    def _translation_fulltext_cache_suffix(self):
        return ""

    def _is_search_active(self):
        return False


def test_unchanged_provider_settings_do_not_trigger_provider_reload():
    providers = {
        "local": {},
        "miniflux": {"url": "https://reader.example", "api_key": "secret"},
    }

    assert not provider_configuration_changed(
        "local",
        providers,
        "local",
        {
            "local": {},
            "miniflux": {"url": "https://reader.example", "api_key": "secret"},
        },
    )


def test_provider_credentials_change_triggers_provider_reload():
    assert provider_configuration_changed(
        "miniflux",
        {"miniflux": {"url": "https://old.example", "api_key": "secret"}},
        "miniflux",
        {"miniflux": {"url": "https://new.example", "api_key": "secret"}},
    )


def test_active_provider_change_triggers_provider_reload():
    providers = {"local": {}, "miniflux": {}}

    assert provider_configuration_changed("local", providers, "miniflux", providers)


def test_no_op_settings_ok_preserves_visible_articles(monkeypatch):
    monkeypatch.setattr(mainframe, "SettingsDialog", _NoOpSettingsDialog)
    host = _SettingsHost()
    visible_articles = host.current_articles

    host.on_settings(None)

    assert host.current_articles is visible_articles
    assert host.list_ctrl.clear_calls == 0
