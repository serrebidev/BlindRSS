# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT
"""Regression tests for the portable.spec build helpers.

The spec cannot be imported (it runs a PyInstaller Analysis at module level),
so the helper is extracted from the spec source and exercised in isolation.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "portable.spec"


def _load_first_existing():
    """Exec only ``first_existing`` from portable.spec and return it."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    node = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "first_existing"
    )
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SPEC), "exec"), namespace)
    return namespace["first_existing"]


def test_first_existing_skips_empty_env_defaults(tmp_path, monkeypatch):
    first_existing = _load_first_existing()
    # Run from a directory that exists so Path("") == "." would match
    # if empty strings were not skipped.
    monkeypatch.chdir(tmp_path)
    assert first_existing([""]) is None


def test_first_existing_prefers_first_real_directory(tmp_path):
    first_existing = _load_first_existing()
    wanted = tmp_path / "vlc" / "plugins"
    wanted.mkdir(parents=True)
    missing = tmp_path / "nope"
    assert first_existing(["", str(missing), str(wanted)]) == wanted


def test_first_existing_returns_none_when_nothing_exists(tmp_path):
    first_existing = _load_first_existing()
    assert first_existing(["", str(tmp_path / "missing")]) is None


def test_linux_vlc_bundle_still_uses_env_overrides():
    text = SPEC.read_text(encoding="utf-8")
    assert "BLINDRSS_VLC_PLUGINS" in text
    assert "BLINDRSS_VLC_LIB_DIR" in text
