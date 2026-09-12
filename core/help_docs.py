# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Load, parse, and flatten the offline user guide (``docs/help/<lang>.md``).

The guide is kept out of the gettext catalogue on purpose: a manual is prose,
not UI strings, and translating it as thousands of tiny msgids would be both
unpleasant for translators and fragile when a paragraph is reworded. Instead
each language is one Markdown file, and a missing language simply falls back to
English — the same fallback rule the UI catalogue uses.

Document format (a deliberately small Markdown subset)::

    # BlindRSS User Guide

    ## Getting Started {#getting-started}

    Prose paragraph.

    - a bullet
    - another bullet

    ### A subsection {#some-anchor}

The ``{#anchor}`` suffix is the stable topic id from ``core.help_topics``; it is
identical in every language, which is what lets context-sensitive F1 jump to the
right section in a translated guide. A heading with no ``{#...}`` still shows up
in the contents list, it just cannot be a jump target.

This module is GUI-free. ``render_plain_text()`` flattens a parsed document into
the linear, punctuation-light text the help window shows in a read-only text
control, plus a map of topic id -> line number for jumping to a section. Line
numbers rather than character offsets because they survive any later change to
how the viewer positions its caret, and they are trivial to assert in a test.
"""
from __future__ import annotations

import os
import re
import sys
from collections import OrderedDict
from typing import Dict, List, Optional, Tuple

HELP_SUBDIR = os.path.join("docs", "help")
FALLBACK_LANGUAGE = "en"

# "## Title {#anchor}" / "### Title" -- anchor optional.
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*(?:\{#([A-Za-z0-9_-]+)\})?\s*$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_EMPHASIS_RE = re.compile(r"(?<!\*)\*([^*\n]+)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")


class Section:
    """One heading and the body lines that follow it."""

    __slots__ = ("anchor", "title", "level", "blocks")

    def __init__(self, anchor: str, title: str, level: int):
        self.anchor = anchor
        self.title = title
        self.level = int(level)
        # (kind, text) with kind in {"text", "bullet", "number", "code"}.
        self.blocks: List[Tuple[str, str]] = []

    def body_text(self) -> str:
        return "\n".join(text for _kind, text in self.blocks)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Section {self.anchor or '-'} {self.title!r} level={self.level}>"


class HelpDocument:
    """A parsed guide: a title plus an ordered list of sections."""

    def __init__(self, language: str, title: str, sections: List[Section], requested: str = ""):
        self.language = language
        self.requested_language = requested or language
        self.title = title
        self.sections = sections

    @property
    def is_fallback(self) -> bool:
        """True when the requested language had no guide and English was used."""
        return _base_language(self.requested_language) != _base_language(self.language)

    def section(self, anchor) -> Optional[Section]:
        wanted = str(anchor or "")
        for section in self.sections:
            if section.anchor == wanted:
                return section
        return None

    def anchors(self) -> List[str]:
        return [s.anchor for s in self.sections if s.anchor]


# --------------------------------------------------------------------------
# Locating the guide files
# --------------------------------------------------------------------------

def help_dirs() -> List[str]:
    """Directories that may hold ``<lang>.md``, most preferred first.

    Mirrors ``core.i18n.locale_dir``: a frozen build unpacks docs/help into the
    PyInstaller payload, a source checkout reads the repository copy.
    """
    dirs = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs.append(os.path.join(base, HELP_SUBDIR))
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    source_dir = os.path.join(repo_root, HELP_SUBDIR)
    if source_dir not in dirs:
        dirs.append(source_dir)
    return dirs


def available_languages() -> List[str]:
    """Language codes with a guide on disk (e.g. ``["en", "hu"]``)."""
    found: List[str] = []
    for directory in help_dirs():
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in entries:
            if not name.lower().endswith(".md"):
                continue
            code = name[:-3]
            if code.lower() == "readme":
                continue
            if code not in found:
                found.append(code)
    return found


def _base_language(code) -> str:
    """``"pt-BR"`` / ``"pt_BR"`` -> ``"pt"``; also lowercases."""
    text = str(code or "").strip().replace("_", "-")
    return text.split("-", 1)[0].lower() if text else ""


def _language_candidates(language) -> List[str]:
    """Codes to try for ``language``, most specific first, English last."""
    text = str(language or "").strip().replace("_", "-")
    candidates: List[str] = []

    def add(value):
        if value and value not in candidates:
            candidates.append(value)

    add(text)
    add(text.replace("-", "_"))
    add(text.lower())
    base = _base_language(text)
    add(base)
    add(FALLBACK_LANGUAGE)
    return candidates


def find_document_path(language) -> Tuple[str, str]:
    """Best ``(path, language)`` for ``language``; ``("", "")`` when none exists."""
    for candidate in _language_candidates(language):
        for directory in help_dirs():
            path = os.path.join(directory, candidate + ".md")
            if os.path.isfile(path):
                return path, candidate
    return "", ""


def load_document(language=FALLBACK_LANGUAGE) -> HelpDocument:
    """Parse the guide for ``language``, falling back to English.

    Never raises: an unreadable or missing guide yields an empty document so the
    help window can say so instead of the app losing F1 entirely.
    """
    path, resolved = find_document_path(language)
    if not path:
        return HelpDocument(FALLBACK_LANGUAGE, "", [], requested=str(language or ""))
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            text = fh.read()
    except OSError:
        return HelpDocument(FALLBACK_LANGUAGE, "", [], requested=str(language or ""))
    document = parse(text, language=resolved)
    document.requested_language = str(language or resolved)
    return document


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def strip_inline_markup(text: str) -> str:
    """Flatten inline Markdown to speech-friendly plain text.

    Links become ``text (url)`` rather than being dropped: a screen-reader user
    reading offline still wants the address, and there is nothing to click in a
    plain text control.
    """
    out = str(text or "")
    out = _LINK_RE.sub(lambda m: f"{m.group(1)} ({m.group(2)})", out)
    out = _BOLD_RE.sub(r"\1", out)
    out = _EMPHASIS_RE.sub(r"\1", out)
    out = _CODE_RE.sub(r"\1", out)
    return out.strip()


def parse(text: str, language: str = FALLBACK_LANGUAGE) -> HelpDocument:
    """Parse the Markdown subset described in the module docstring."""
    title = ""
    sections: List[Section] = []
    current: Optional[Section] = None
    in_code_block = False
    paragraph: List[str] = []

    def flush_paragraph():
        if paragraph and current is not None:
            current.blocks.append(("text", strip_inline_markup(" ".join(paragraph))))
        del paragraph[:]

    for raw_line in str(text or "").splitlines():
        line = raw_line.rstrip()

        if line.strip().startswith("```"):
            flush_paragraph()
            in_code_block = not in_code_block
            continue
        if in_code_block:
            if current is not None:
                current.blocks.append(("code", raw_line))
            continue

        if not line.strip():
            flush_paragraph()
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            level = len(heading.group(1))
            heading_title = strip_inline_markup(heading.group(2))
            anchor = heading.group(3) or ""
            if level == 1 and not sections and not anchor:
                # A bare "# Title" before the first anchored section is the
                # document title, not a section of its own.
                title = heading_title
                continue
            current = Section(anchor, heading_title, level)
            sections.append(current)
            if level == 1 and not title:
                title = heading_title
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            if current is not None:
                current.blocks.append(("bullet", strip_inline_markup(bullet.group(1))))
            continue

        numbered = _NUMBERED_RE.match(line)
        if numbered:
            flush_paragraph()
            if current is not None:
                current.blocks.append(
                    ("number", f"{numbered.group(1)}. {strip_inline_markup(numbered.group(2))}")
                )
            continue

        paragraph.append(line.strip())

    flush_paragraph()
    return HelpDocument(language, title, sections)


# --------------------------------------------------------------------------
# Flattening for the viewer
# --------------------------------------------------------------------------

def render_plain_text(document: HelpDocument) -> Tuple[str, Dict[str, int], List[int]]:
    """Flatten ``document`` to ``(text, {anchor: line}, [line per section])``.

    Line numbers are zero-based. The per-section list runs parallel to
    ``contents_entries()``, so the contents list can jump to a heading that
    carries no ``{#anchor}`` just as well as to one that does.

    Bullets keep a leading "- " so a screen reader announces them as list items
    rather than running them into the previous sentence, and every heading is
    preceded by a blank line so line-by-line reading has an audible boundary.
    """
    lines: List[str] = []
    offsets: "OrderedDict[str, int]" = OrderedDict()
    section_lines: List[int] = []

    first_title = document.sections[0].title if document.sections else ""
    if document.title and document.title != first_title:
        # A guide whose first section repeats the document title (the common
        # case) should not read it out twice.
        lines.append(document.title)
        lines.append("")

    for section in document.sections:
        if lines and lines[-1] != "":
            lines.append("")
        section_lines.append(len(lines))
        if section.anchor:
            offsets[section.anchor] = len(lines)
        lines.append(section.title)
        lines.append("")
        for kind, text in section.blocks:
            if kind == "bullet":
                lines.append(f"- {text}")
            elif kind == "code":
                lines.append(f"    {text}")
            else:
                lines.append(text)
                lines.append("")
        while lines and lines[-1] == "":
            lines.pop()

    return "\n".join(lines) + "\n", dict(offsets), section_lines


def contents_entries(document: HelpDocument) -> List[Tuple[str, str, int]]:
    """``(anchor, display title, level)`` for the help window's contents list."""
    entries = []
    for section in document.sections:
        entries.append((section.anchor, section.title, section.level))
    return entries
