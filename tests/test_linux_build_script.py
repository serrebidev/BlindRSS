# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_linux_build_checks_project_syntax_before_dependency_warning_filter():
    script = (ROOT / "tools" / "build_linux_docker.sh").read_text(
        encoding="utf-8"
    )

    strict_check = "-W error::SyntaxWarning -m py_compile"
    dependency_filter = (
        "PYTHONWARNINGS='ignore:invalid escape sequence:SyntaxWarning'"
    )

    assert strict_check in script
    assert dependency_filter in script
    assert script.index(strict_check) < script.index(dependency_filter)
    assert "SyntaxWarning:pyautogui._pyautogui_x11" not in script
