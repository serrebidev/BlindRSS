# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Compile gettext .po catalogs to .mo, with no GNU gettext dependency.

Lives in core/ (not tools/) because the frozen app needs it too: only compiled
.mo files are bundled by the PyInstaller specs, so over-the-air translation
updates download the .po text and compile it on the user's machine
(see core/translation_updates.py). tools/compile_translations.py re-exports
these for the build so there is exactly one implementation.

Supports the PO shapes produced by tools/extract_strings.py and common PO
editors: continued strings, plural msgstr[n] entries, and fuzzy-entry skipping.
"""

from __future__ import annotations

import ast
import re
import struct
from pathlib import Path


DOMAIN = "blindrss"


def _po_unquote(token: str) -> str:
    return ast.literal_eval(token.strip())


def _new_entry() -> dict:
    return {
        "msgid": None,
        "msgid_plural": None,
        "msgstr": {},
        "flags": set(),
    }


def _finish_entry(
    entry: dict,
    messages: dict[str, str],
    required_plural_forms: int | None,
) -> int | None:
    msgid = entry.get("msgid")
    if msgid is None or "fuzzy" in entry.get("flags", set()):
        return required_plural_forms

    plural = entry.get("msgid_plural")
    msgstr = entry.get("msgstr") or {}
    if plural is None:
        value = msgstr.get(0, "")
        # An empty translation is intentionally untranslated. Omitting it from
        # the MO lets gettext fall back to the English msgid; storing an empty
        # value instead makes the corresponding control text disappear.
        if not value.strip():
            return required_plural_forms
        messages[msgid] = value
        if msgid == "":
            match = re.search(
                r"(?:^|\n)Plural-Forms:\s*nplurals\s*=\s*(\d+)",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                required_plural_forms = max(1, int(match.group(1)))
        return required_plural_forms

    indexes = sorted(i for i in msgstr if isinstance(i, int))
    if not indexes:
        return required_plural_forms
    expected_count = required_plural_forms or (indexes[-1] + 1)
    if indexes != list(range(expected_count)):
        return required_plural_forms
    values = [msgstr.get(i, "") for i in range(expected_count)]
    # A partially translated plural entry is just as unsafe as an empty
    # singular entry: some counts would otherwise render as blank text.
    if any(not value.strip() for value in values):
        return required_plural_forms
    messages[f"{msgid}\0{plural}"] = "\0".join(values)
    return required_plural_forms


def parse_po_text(text: str) -> dict[str, str]:
    """Parse PO source text into the msgid -> msgstr map a .mo stores."""
    messages: dict[str, str] = {}
    entry = _new_entry()
    active: tuple[str, int | None] | None = None
    required_plural_forms: int | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            required_plural_forms = _finish_entry(
                entry,
                messages,
                required_plural_forms,
            )
            entry = _new_entry()
            active = None
            continue
        if line.startswith("#,"):
            entry["flags"].update(flag.strip() for flag in line[2:].split(","))
            continue
        if line.startswith("#"):
            continue

        if line.startswith("msgid_plural"):
            entry["msgid_plural"] = _po_unquote(line.split(None, 1)[1])
            active = ("msgid_plural", None)
        elif line.startswith("msgid"):
            entry["msgid"] = _po_unquote(line.split(None, 1)[1])
            active = ("msgid", None)
        elif line.startswith("msgstr["):
            end = line.index("]")
            index = int(line[len("msgstr["):end])
            entry["msgstr"][index] = _po_unquote(line[end + 1:].strip())
            active = ("msgstr", index)
        elif line.startswith("msgstr"):
            entry["msgstr"][0] = _po_unquote(line.split(None, 1)[1])
            active = ("msgstr", 0)
        elif line.startswith('"') and active is not None:
            value = _po_unquote(line)
            field, index = active
            if field == "msgstr":
                entry["msgstr"][index or 0] = entry["msgstr"].get(index or 0, "") + value
            else:
                entry[field] = (entry.get(field) or "") + value

    _finish_entry(entry, messages, required_plural_forms)
    return messages


def read_po(path: Path) -> dict[str, str]:
    return parse_po_text(Path(path).read_text(encoding="utf-8-sig"))


def write_mo(messages: dict[str, str], path: Path) -> None:
    path = Path(path)
    ids = sorted(messages)
    originals = []
    translations = []

    offset = 7 * 4 + len(ids) * 16
    original_table = []
    for msgid in ids:
        data = msgid.encode("utf-8")
        original_table.append((len(data), offset))
        originals.append(data + b"\0")
        offset += len(data) + 1

    translation_table = []
    for msgid in ids:
        data = messages[msgid].encode("utf-8")
        translation_table.append((len(data), offset))
        translations.append(data + b"\0")
        offset += len(data) + 1

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(
            struct.pack(
                "Iiiiiii",
                0x950412DE,
                0,
                len(ids),
                7 * 4,
                7 * 4 + len(ids) * 8,
                0,
                0,
            )
        )
        for length, table_offset in original_table:
            fh.write(struct.pack("ii", length, table_offset))
        for length, table_offset in translation_table:
            fh.write(struct.pack("ii", length, table_offset))
        for data in originals:
            fh.write(data)
        for data in translations:
            fh.write(data)


def compile_catalog(po_path: Path) -> Path:
    po_path = Path(po_path)
    mo_path = po_path.with_suffix(".mo")
    write_mo(read_po(po_path), mo_path)
    return mo_path


def iter_catalogs(locale_root: Path) -> list[Path]:
    locale_root = Path(locale_root)
    if not locale_root.is_dir():
        return []
    return sorted(locale_root.glob(f"*/LC_MESSAGES/{DOMAIN}.po"))
