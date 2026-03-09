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


def test_migrate_old_refresh_defaults_to_low_cpu_defaults(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 10,
            "per_host_max_connections": 4,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 3
    assert int(mgr.get("per_host_max_connections")) == 1

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 3
    assert int(saved.get("per_host_max_connections")) == 1


def test_custom_refresh_values_are_not_overwritten_by_migration(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    _write_json(
        cfg_path,
        {
            "max_concurrent_refreshes": 6,
            "per_host_max_connections": 2,
        },
    )

    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()

    assert int(mgr.get("max_concurrent_refreshes")) == 6
    assert int(mgr.get("per_host_max_connections")) == 2

    saved = _read_json(cfg_path)
    assert int(saved.get("max_concurrent_refreshes")) == 6
    assert int(saved.get("per_host_max_connections")) == 2
