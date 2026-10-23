# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Guard the bleeding-edge trafilatura policy (owner rule, 2026-10-22).

trafilatura must track upstream git master, never a PyPI version pin:
extraction fixes land on master weeks before a release. Every install
path (requirements.txt + both build scripts' upgrade steps) must carry
the git reference, so a silent regression to a pin fails the suite.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_REF = "trafilatura@git+https://github.com/adbar/trafilatura.git@master"


def _lines(name):
    return (ROOT / name).read_text(encoding="utf-8").splitlines()


def test_requirements_tracks_git_master_not_a_pin():
    lines = [ln.strip() for ln in _lines("requirements.txt")]
    assert GIT_REF in lines
    assert not any(ln.startswith("trafilatura>=") for ln in lines)
    assert not any(ln.startswith("trafilatura=") for ln in lines)


def test_build_scripts_reinstall_trafilatura_from_git_master():
    for name in ("build.bat", "build.sh"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert GIT_REF in text, f"{name} lost the git-master reinstall step"
