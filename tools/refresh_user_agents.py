# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Refresh the baked-in User-Agent versions in core/user_agents.py.

Run from build.bat at release time. The build machine's installed browsers are
the source: whatever Chromium and Gecko majors it is running become the strings
shipped to users whose own machines have no detectable browser.

Fails soft on purpose. A build machine without a browser, or one whose browsers
are older than what is already committed, must not downgrade the shipped
defaults or break the release; the script reports and exits 0.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TARGET = os.path.join(REPO_ROOT, "core", "user_agents.py")

_ASSIGN_RE = {
    "CHROMIUM_MAJOR": re.compile(r'^(CHROMIUM_MAJOR\s*=\s*")(\d+)(")$', re.MULTILINE),
    "FIREFOX_MAJOR": re.compile(r'^(FIREFOX_MAJOR\s*=\s*")(\d+)(")$', re.MULTILINE),
}


def detected_majors() -> dict:
    """Highest Chromium and Gecko majors installed on this machine."""
    from core import user_agents

    majors = {"CHROMIUM_MAJOR": 0, "FIREFOX_MAJOR": 0}
    for identity in user_agents.detect_installed(refresh=True):
        match = re.search(r"Firefox/(\d+)", identity.ua)
        if match:
            majors["FIREFOX_MAJOR"] = max(majors["FIREFOX_MAJOR"], int(match.group(1)))
            continue
        match = re.search(r"Chrome/(\d+)", identity.ua)
        if match:
            majors["CHROMIUM_MAJOR"] = max(majors["CHROMIUM_MAJOR"], int(match.group(1)))
    return majors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report what would change without writing.",
    )
    args = parser.parse_args()

    try:
        with open(TARGET, "r", encoding="utf-8") as fh:
            source = fh.read()
    except OSError as exc:
        print(f"[user-agents] Could not read {TARGET}: {exc}")
        return 0

    try:
        found = detected_majors()
    except Exception as exc:  # pragma: no cover - build-machine variance
        print(f"[user-agents] Browser detection failed ({exc}); keeping committed versions.")
        return 0

    updated = source
    changes = []
    for name, pattern in _ASSIGN_RE.items():
        match = pattern.search(updated)
        if not match:
            print(f"[user-agents] {name} not found in core/user_agents.py; skipping.")
            continue
        current = int(match.group(2))
        detected = found.get(name, 0)
        if detected <= current:
            continue
        changes.append(f"{name}: {current} -> {detected}")
        updated = pattern.sub(rf"\g<1>{detected}\g<3>", updated, count=1)

    if not changes:
        print("[user-agents] Committed browser versions are already current.")
        return 0

    if args.check:
        print("[user-agents] Would update " + "; ".join(changes))
        return 0

    try:
        with open(TARGET, "w", encoding="utf-8") as fh:
            fh.write(updated)
    except OSError as exc:
        print(f"[user-agents] Could not write {TARGET}: {exc}")
        return 0

    print("[user-agents] Updated " + "; ".join(changes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
