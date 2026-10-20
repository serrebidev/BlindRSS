"""config.json must never be left half-written or silently reset."""

import json

import core.config as config_mod


def test_save_failure_leaves_previous_config_intact(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    mgr = config_mod.ConfigManager()
    mgr.set("language", "fr")

    class Unserializable:
        pass

    mgr.config["broken"] = Unserializable()
    mgr.save_config()  # logs, must not truncate the good file
    assert json.loads(cfg_path.read_text(encoding="utf-8"))["language"] == "fr"
    assert not (tmp_path / "config.json.tmp").exists()


def test_unreadable_config_is_kept_before_defaults_overwrite_it(tmp_path, monkeypatch):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text('{"language": "fr", "providers": {', encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_FILE", str(cfg_path))
    config_mod.ConfigManager()
    kept = list(tmp_path.glob("config.json.corrupt-*"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8").startswith('{"language": "fr"')
