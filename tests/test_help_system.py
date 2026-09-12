# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The offline user guide and context-sensitive F1.

The point of these tests is that F1 cannot quietly degrade. Every mapping table
in ``core.help_topics`` is checked against the sections that actually exist in
``docs/help/en.md``, every shortcut command must name a topic, and every
translated guide must carry the same anchors as the English one — so adding a
command, renaming a section, or translating the guide either works or fails
loudly here.
"""
import os
import sys

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import help_docs, help_topics, shortcuts


@pytest.fixture(scope="module")
def english_guide():
    document = help_docs.load_document("en")
    assert document.sections, "docs/help/en.md did not parse into any sections"
    return document


# --------------------------------------------------------------------------
# The guide matches the registry
# --------------------------------------------------------------------------

def test_every_topic_has_a_section(english_guide):
    anchors = set(english_guide.anchors())
    missing = [topic for topic in help_topics.topic_ids() if topic not in anchors]
    assert not missing, f"topics with no section in docs/help/en.md: {missing}"


def test_every_section_is_a_known_topic(english_guide):
    known = set(help_topics.topic_ids())
    unknown = [anchor for anchor in english_guide.anchors() if anchor not in known]
    assert not unknown, f"sections in docs/help/en.md with no topic id: {unknown}"


def test_anchors_are_unique(english_guide):
    anchors = english_guide.anchors()
    duplicates = sorted({a for a in anchors if anchors.count(a) > 1})
    assert not duplicates, f"duplicate anchors in docs/help/en.md: {duplicates}"


def test_default_topic_exists(english_guide):
    assert english_guide.section(help_topics.DEFAULT_TOPIC) is not None


def test_every_section_has_body_text(english_guide):
    empty = [s.anchor or s.title for s in english_guide.sections if not s.body_text().strip()]
    assert not empty, f"sections with no content: {empty}"


# --------------------------------------------------------------------------
# The mapping tables point at real topics
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "table_name",
    ["COMMAND_TOPICS", "DIALOG_TOPICS", "MENU_TITLE_TOPICS", "CONTEXT_MENU_TOPICS",
     "NOTEBOOK_PAGE_TOPICS"],
)
def test_mapping_targets_are_known_topics(table_name):
    table = getattr(help_topics, table_name)
    bad = sorted({topic for topic in table.values() if not help_topics.is_known_topic(topic)})
    assert not bad, f"{table_name} points at topics that do not exist: {bad}"


def test_every_shortcut_command_has_a_topic():
    """A new command must be documented, not silently fall back to the front page."""
    unmapped = [c.id for c in shortcuts.COMMANDS if c.id not in help_topics.COMMAND_TOPICS]
    assert not unmapped, (
        "shortcut commands with no help topic (add them to "
        f"core.help_topics.COMMAND_TOPICS): {unmapped}"
    )


def test_command_topics_name_real_commands():
    known = {c.id for c in shortcuts.COMMANDS}
    stale = sorted(set(help_topics.COMMAND_TOPICS) - known)
    assert not stale, f"COMMAND_TOPICS entries for commands that no longer exist: {stale}"


def test_user_guide_command_defaults_to_f1():
    command = next(c for c in shortcuts.COMMANDS if c.id == "help.user_guide")
    assert command.default == "F1"
    assert command.category == "Help"


def test_normalize_falls_back_for_unknown_topics():
    assert help_topics.normalize("no-such-topic") == help_topics.DEFAULT_TOPIC
    assert help_topics.normalize(None) == help_topics.DEFAULT_TOPIC
    assert help_topics.normalize("player") == "player"


def test_topic_for_class_names_walks_the_mro():
    assert help_topics.topic_for_class_names(["NotADialog", "SettingsDialog"]) == "settings"
    assert help_topics.topic_for_class_names(["NotADialog"]) is None


# --------------------------------------------------------------------------
# Document loading, fallback, and rendering
# --------------------------------------------------------------------------

def test_unknown_language_falls_back_to_english():
    document = help_docs.load_document("qq")
    assert document.language == "en"
    assert document.is_fallback


def test_english_is_not_reported_as_a_fallback():
    assert not help_docs.load_document("en").is_fallback


def test_regional_language_falls_back_to_its_base(tmp_path, monkeypatch):
    (tmp_path / "pt.md").write_text(
        "# Guia\n\n## Bem-vindo {#user-guide}\n\nTexto.\n", encoding="utf-8"
    )
    monkeypatch.setattr(help_docs, "help_dirs", lambda: [str(tmp_path)])
    document = help_docs.load_document("pt-BR")
    assert document.language == "pt"
    assert document.section("user-guide") is not None
    # Same base language, so this is a regional variant, not an English fallback.
    assert not document.is_fallback


def test_missing_guide_directory_yields_an_empty_document(tmp_path, monkeypatch):
    monkeypatch.setattr(help_docs, "help_dirs", lambda: [str(tmp_path / "nope")])
    document = help_docs.load_document("en")
    assert document.sections == []
    text, anchors, section_lines = help_docs.render_plain_text(document)
    assert text.strip() == ""
    assert anchors == {}
    assert section_lines == []


def test_parse_reads_the_supported_markdown_subset():
    document = help_docs.parse(
        "# Title\n"
        "\n"
        "## First {#getting-started}\n"
        "\n"
        "A paragraph that\n"
        "wraps across lines.\n"
        "\n"
        "- **bold** bullet\n"
        "- a [link](https://example.com)\n"
        "\n"
        "1. step one\n"
        "\n"
        "### Deeper {#player}\n"
        "\n"
        "Body.\n"
    )
    assert document.title == "Title"
    assert [s.anchor for s in document.sections] == ["getting-started", "player"]
    assert document.sections[0].level == 2
    assert document.sections[1].level == 3
    blocks = document.sections[0].blocks
    assert ("text", "A paragraph that wraps across lines.") in blocks
    assert ("bullet", "bold bullet") in blocks
    assert ("bullet", "a link (https://example.com)") in blocks
    assert ("number", "1. step one") in blocks


def test_heading_without_an_anchor_still_becomes_a_section():
    document = help_docs.parse("# T\n\n## Anchored {#player}\n\nA.\n\n## Bare\n\nB.\n")
    assert [s.title for s in document.sections] == ["Anchored", "Bare"]
    assert document.anchors() == ["player"]


def test_render_maps_every_anchor_to_its_heading_line(english_guide):
    text, anchors, section_lines = help_docs.render_plain_text(english_guide)
    lines = text.split("\n")
    assert len(section_lines) == len(english_guide.sections)
    for section in english_guide.sections:
        line = anchors[section.anchor]
        assert lines[line] == section.title, (
            f"anchor {section.anchor} points at {lines[line]!r}, not its heading"
        )


def test_render_does_not_repeat_the_document_title(english_guide):
    text, _anchors, _lines = help_docs.render_plain_text(english_guide)
    lines = [line for line in text.split("\n") if line.strip()]
    assert lines[0] == english_guide.sections[0].title
    assert lines.count(english_guide.title) == 1


def test_strip_inline_markup_keeps_link_targets():
    assert help_docs.strip_inline_markup("see [docs](https://x.example)") == (
        "see docs (https://x.example)"
    )
    assert help_docs.strip_inline_markup("**a** *b* `c`") == "a b c"


# --------------------------------------------------------------------------
# Translated guides stay in step with the English one
# --------------------------------------------------------------------------

def _translated_guide_paths():
    directory = os.path.join(REPO_ROOT, "docs", "help")
    if not os.path.isdir(directory):
        return []
    return [
        os.path.join(directory, name)
        for name in sorted(os.listdir(directory))
        if name.endswith(".md") and name not in ("en.md", "README.md")
    ]


@pytest.mark.parametrize("path", _translated_guide_paths())
def test_translated_guide_has_the_same_anchors(path, english_guide):
    with open(path, "r", encoding="utf-8-sig") as handle:
        document = help_docs.parse(handle.read())
    expected = set(english_guide.anchors())
    actual = set(document.anchors())
    assert not (expected - actual), (
        f"{os.path.basename(path)} is missing anchors: {sorted(expected - actual)}"
    )
    assert not (actual - expected), (
        f"{os.path.basename(path)} has unknown anchors: {sorted(actual - expected)}"
    )
