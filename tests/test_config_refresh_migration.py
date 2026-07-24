# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.config as config_mod


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_migrate_old_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 10,
            "per_host_max_connections": 4,
            "feed_retry_attempts": 5,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_migrate_previous_low_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 6,
            "per_host_max_connections": 2,
            "feed_retry_attempts": 5,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_migrate_older_low_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 3,
            "per_host_max_connections": 1,
            "feed_retry_attempts": 5,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_migrate_previous_high_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 12,
            "per_host_max_connections": 4,
            "feed_retry_attempts": 5,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_migrate_previous_balanced_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 8,
            "per_host_max_connections": 2,
            "feed_retry_attempts": 1,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_migrate_shipped_v1_73_1_refresh_defaults_to_current_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 6,
            "per_host_max_connections": 2,
            "feed_retry_attempts": 1,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 16
    assert int(mgr.get("per_host_max_connections")) == 4
    assert int(mgr.get("feed_retry_attempts")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 16
    assert int(saved.get("per_host_max_connections")) == 4
    assert int(saved.get("feed_retry_attempts")) == 1


def test_custom_refresh_values_are_not_overwritten_by_migration(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 8,
            "per_host_max_connections": 3,
            "feed_retry_attempts": 2,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 8
    assert int(mgr.get("per_host_max_connections")) == 3
    assert int(mgr.get("feed_retry_attempts")) == 2

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 8
    assert int(saved.get("per_host_max_connections")) == 3
    assert int(saved.get("feed_retry_attempts")) == 2
