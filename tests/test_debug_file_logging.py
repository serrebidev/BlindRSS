# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import logging
import os
import sys


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import core.config as config_mod
import main


class _Config:
    def __init__(self, debug_mode):
        self.debug_mode = bool(debug_mode)

    def get(self, key, default=None):
        if key == "debug_mode":
            return self.debug_mode
        return default


def _remove_blindrss_file_handlers():
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_blindrss_file_handler", False):
            root.removeHandler(handler)
            handler.close()


def test_debug_file_logging_disabled_does_not_create_log(tmp_path, monkeypatch):
    _remove_blindrss_file_handlers()
    monkeypatch.setattr(config_mod, "get_data_dir", lambda: str(tmp_path))

    log_path = main._configure_file_logging(_Config(debug_mode=False))

    assert log_path is None
    assert not (tmp_path / "blindrss.log").exists()
    assert not [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, "_blindrss_file_handler", False)
    ]


def test_debug_file_logging_enabled_captures_debug_messages(tmp_path, monkeypatch):
    root = logging.getLogger()
    old_root_level = root.level
    old_trafilatura_level = logging.getLogger("trafilatura").level
    old_readability_level = logging.getLogger("readability").level
    _remove_blindrss_file_handlers()
    monkeypatch.setattr(config_mod, "get_data_dir", lambda: str(tmp_path))

    try:
        log_path = main._configure_file_logging(_Config(debug_mode=True))
        logger = logging.getLogger("tests.debug_file_logging")
        logger.debug("debug marker from test")

        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_path == str(tmp_path / "blindrss.log")
        assert "debug marker from test" in (tmp_path / "blindrss.log").read_text(encoding="utf-8")
        assert root.level == logging.DEBUG
        assert logging.getLogger("trafilatura").level == logging.NOTSET
        assert logging.getLogger("readability").level == logging.NOTSET
    finally:
        _remove_blindrss_file_handlers()
        root.setLevel(old_root_level)
        logging.getLogger("trafilatura").setLevel(old_trafilatura_level)
        logging.getLogger("readability").setLevel(old_readability_level)
