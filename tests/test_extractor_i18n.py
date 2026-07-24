# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Extraction messages must translate at raise time, not import time (PR #69).

core.article_extractor is imported (via gui.mainframe) from main.py's import
block, which runs BEFORE main.py calls i18n.setup(). Any module-level
``MSG = _("...")`` therefore captures the English NullTranslations fallback
permanently -- which is precisely why PR #69's translations never appeared even
though its ru catalog was correct.

These tests pin the two halves of the fix: the messages resolve through a live
catalog installed AFTER import, and no module-level constant re-freezes them.
"""

import ast
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from core import article_extractor, i18n

_EXTRACTOR_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core",
    "article_extractor.py",
)

MESSAGE_FUNCS = (
    article_extractor._blocked_interstitial_message,
    article_extractor._link_list_only_message,
    article_extractor._paywall_message,
    article_extractor._google_news_resolution_message,
)


@pytest.fixture
def russian_catalog():
    """Install ru the way the app does: long after this module was imported."""
    i18n.setup("ru")
    yield
    i18n.setup("en")


def test_messages_translate_after_a_late_setup(russian_catalog):
    for func in MESSAGE_FUNCS:
        message = func()
        assert message, f"{func.__name__} returned an empty message"
        # Cyrillic presence is the cheap, catalog-agnostic proof that the
        # message came from the catalog rather than the English fallback.
        assert any("Ѐ" <= ch <= "ӿ" for ch in message), (
            f"{func.__name__} was not translated -- it was almost certainly "
            f"frozen at import time: {message[:60]!r}"
        )


def test_messages_are_recomputed_per_call(russian_catalog):
    """A language change must re-label existing messages, so no memoization."""
    russian = article_extractor._paywall_message()
    i18n.setup("en")
    english = article_extractor._paywall_message()
    assert russian != english
    assert "paywall" in english


def test_no_module_level_gettext_calls_in_the_extractor():
    """Guard the contract itself: a future edit that hoists _() back up to
    module level would silently un-translate these messages again."""
    tree = ast.parse(io.open(_EXTRACTOR_PATH, encoding="utf-8").read())
    offenders = []

    for node in tree.body:  # module level only -- nested defs are fine
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id in ("_", "ngettext")
            ):
                offenders.append(f"line {child.lineno}")

    assert not offenders, (
        "module-level _() in core/article_extractor.py at "
        + ", ".join(offenders)
        + " -- this module is imported before i18n.setup(), so the value freezes "
        "to English. Wrap the message in a function instead (see PR #69)."
    )
