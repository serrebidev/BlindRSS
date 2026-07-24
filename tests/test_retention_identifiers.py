# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Retention settings use stable identifiers, not UI labels (issue #63)."""

import json
import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.config as config_mod
from core.retention import (
    RETENTION_CHOICES,
    RETENTION_DEFAULT,
    normalize_retention,
    retention_days,
    retention_label,
    retention_seconds,
)


def test_identifiers_pass_through_unchanged():
    for ident, _days in RETENTION_CHOICES:
        assert normalize_retention(ident) == ident


def test_legacy_english_labels_map_to_identifiers():
    assert normalize_retention("1 day") == "1_day"
    assert normalize_retention("1 week") == "1_week"
    assert normalize_retention("6 months") == "6_months"
    assert normalize_retention("5 years") == "5_years"
    assert normalize_retention("Unlimited") == "unlimited"
    # Early builds accepted these labels even though the UI never offered them.
    assert normalize_retention("2 days") == "2_days"
    assert normalize_retention("3 months") == "3_months"


def test_unknown_values_fall_back_to_unlimited():
    # The safe direction: never delete more than the user asked for.
    assert normalize_retention("1 semana") == RETENTION_DEFAULT
    assert normalize_retention("") == RETENTION_DEFAULT
    assert normalize_retention(None) == RETENTION_DEFAULT
    assert retention_days("garbage") is None
    assert retention_seconds("garbage") is None


def test_days_and_seconds():
    assert retention_days("1_day") == 1
    assert retention_days("1 week") == 7
    assert retention_days("2_years") == 730
    assert retention_days("unlimited") is None
    assert retention_seconds("3 days") == 3 * 86400
    assert retention_seconds("unlimited") is None


def test_every_choice_has_a_label():
    for ident, _days in RETENTION_CHOICES:
        assert retention_label(ident)
    assert retention_label("3_months")
    assert retention_label("2_days")


def test_config_migration_converts_legacy_labels(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(
            {"article_retention": "1 week", "download_retention": "Unlimited"}, f
        )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert mgr.get("article_retention") == "1_week"
    assert mgr.get("download_retention") == "unlimited"

    with open(cfg_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["article_retention"] == "1_week"
    assert saved["download_retention"] == "unlimited"


def test_config_migration_keeps_identifier_values(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(
            {"article_retention": "3_days", "download_retention": "1_year"}, f
        )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert mgr.get("article_retention") == "3_days"
    assert mgr.get("download_retention") == "1_year"


def test_mainframe_retention_seconds_accepts_both_forms():
    import gui.mainframe as mainframe

    class _Host:
        _retention_seconds = mainframe.MainFrame._retention_seconds

    host = _Host()
    assert host._retention_seconds("1_week") == 7 * 86400
    assert host._retention_seconds("1 week") == 7 * 86400
    assert host._retention_seconds("Unlimited") is None
    assert host._retention_seconds("unlimited") is None
