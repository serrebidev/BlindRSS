# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import runtime_self_test


def test_runtime_import_list_covers_macos_fulltext_stack():
    required = set(runtime_self_test._REQUIRED_MODULES)
    assert {
        "core.article_extractor",
        "core.article_html",
        "gui.accessibility",
        "curl_cffi",
        "markdown",
        "pydoll.browser.chromium",
        "seleniumbase",
        "trafilatura",
        "wx.html2",
        "wx_accessible_webview",
    } <= required


def test_runtime_self_test_reports_every_failed_area(monkeypatch, capsys):
    monkeypatch.setattr(runtime_self_test.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_self_test, "_check_imports", lambda: ["imports"])
    monkeypatch.setattr(runtime_self_test, "_check_fulltext", lambda: ["fulltext"])
    monkeypatch.setattr(runtime_self_test, "_check_tools", lambda: ["tools"])
    monkeypatch.setattr(runtime_self_test, "_check_vlc", lambda: ["vlc"])
    monkeypatch.setattr(runtime_self_test, "_check_update_support", lambda: ["update"])

    assert runtime_self_test.run_runtime_self_test() == 1
    stderr = capsys.readouterr().err
    for area in ("imports", "fulltext", "tools", "vlc", "update"):
        assert f"Runtime self-test failed: {area}" in stderr


def test_runtime_self_test_passes_when_all_checks_pass(monkeypatch, capsys):
    monkeypatch.setattr(runtime_self_test.sys, "frozen", True, raising=False)
    monkeypatch.setattr(runtime_self_test, "_check_imports", lambda: [])
    monkeypatch.setattr(runtime_self_test, "_check_fulltext", lambda: [])
    monkeypatch.setattr(runtime_self_test, "_check_tools", lambda: [])
    monkeypatch.setattr(runtime_self_test, "_check_vlc", lambda: [])
    monkeypatch.setattr(runtime_self_test, "_check_update_support", lambda: [])

    assert runtime_self_test.run_runtime_self_test() == 0
    assert capsys.readouterr().out == "Runtime self-test passed.\n"


def test_runtime_fulltext_check_is_repeatable():
    assert runtime_self_test._check_fulltext() == []
