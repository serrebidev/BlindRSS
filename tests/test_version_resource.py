# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The version a screen reader reports for BlindRSS.

Two independent paths answer "what version is this?":

* the Windows VERSIONINFO resource stamped into the built exe, which NVDA's
  app-version command and the JAWS equivalent read (an unstamped exe is what
  makes a screen reader say "Application unknown, version not detected");
* the in-app Announce Version command, which speaks it outright.

These tests cover the rules behind both without needing a build or a wx.App.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.version import APP_VERSION
from tools import verify_version_resource as vvr

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _good_values(version=APP_VERSION):
    return {
        "ProductName": "BlindRSS",
        "ProductVersion": version,
        "FileVersion": version,
        "FileDescription": "BlindRSS",
    }


def test_read_app_version_matches_the_app():
    assert vvr.read_app_version(REPO_ROOT) == APP_VERSION


def test_correct_stamp_has_no_problems():
    assert vvr.check_version_strings(_good_values(), APP_VERSION) == []


def test_missing_resource_is_reported_in_the_users_words():
    """An exe with no resource is exactly the "version not detected" case."""
    problems = vvr.check_version_strings({}, APP_VERSION)
    assert len(problems) == 1
    assert "version not detected" in problems[0]


def test_stale_version_fails():
    problems = vvr.check_version_strings(_good_values("1.0.0"), APP_VERSION)
    assert any("ProductVersion" in p and "1.0.0" in p for p in problems)
    assert any("FileVersion" in p for p in problems)


def test_wrong_product_name_fails():
    values = _good_values()
    values["ProductName"] = "main"
    problems = vvr.check_version_strings(values, APP_VERSION)
    assert any("ProductName" in p for p in problems)


def test_each_required_key_must_be_present_and_non_empty():
    for key in vvr.REQUIRED_KEYS:
        values = _good_values()
        values[key] = "   "
        problems = vvr.check_version_strings(values, APP_VERSION)
        assert any(key in p and "missing or empty" in p for p in problems), key


def test_both_windows_specs_stamp_the_resource():
    """Guard the stamp itself: without it the built exe is anonymous.

    main.spec builds every Windows release; portable.spec is the
    cross-platform spec and stamps the same resource when it runs on Windows.
    """
    for spec in ("main.spec", "portable.spec"):
        with open(os.path.join(REPO_ROOT, spec), "r", encoding="utf-8") as fh:
            text = fh.read()
        assert "VSVersionInfo" in text, f"{spec}: no version resource"
        assert re.search(r"StringStruct\(\s*'ProductName',\s*'BlindRSS'", text), spec
        assert re.search(
            r"StringStruct\(\s*'ProductVersion',\s*_app_version", text
        ), f"{spec}: ProductVersion must come from core/version.py"


def test_announce_version_speaks_the_running_version():
    import gui.mainframe as mainframe

    announced = []

    class _Host:
        _cmd_announce_version = mainframe.MainFrame._cmd_announce_version

        def _announce_event(self, event_id, message):
            announced.append((event_id, message))

    _Host()._cmd_announce_version()

    assert len(announced) == 1
    event_id, message = announced[0]
    assert event_id == "general"
    assert APP_VERSION in message
    assert "BlindRSS" in message


def test_announce_version_command_is_registered_and_bound():
    from core import shortcuts as sc

    cmd = sc.command_by_id("tools.announce_version")
    assert cmd is not None
    # Ships bound: a user who wants the version should not have to configure a
    # key first. It must not collide with any other default.
    assert cmd.default
    assert sc.find_conflicts(sc.default_bindings()) == {}
