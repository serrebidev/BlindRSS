# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shadow of pyinstaller-hooks-contrib's hook-pycparser.

The contrib hook unconditionally declares ``pycparser.lextab`` and
``pycparser.yacctab`` as hidden imports because old pycparser generated those
table modules at runtime. pycparser 3.00 (installed here) no longer ships or
generates them, so the contrib hook produces two build warnings:

    WARNING: Hidden import "pycparser.lextab" not found!
    WARNING: Hidden import "pycparser.yacctab" not found!

This user hook (hookspath has priority over contrib hooks) declares the same
hidden imports only when the modules actually exist, keeping older pycparser
versions working while silencing the warnings on 3.00+.
"""

from __future__ import annotations

import importlib.util

hiddenimports = []
for _mod in ("pycparser.lextab", "pycparser.yacctab"):
    try:
        if importlib.util.find_spec(_mod) is not None:
            hiddenimports.append(_mod)
    except Exception:
        pass
