# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import gettext
from pathlib import Path
from string import Formatter

from tools import compile_translations


def test_compile_catalog_writes_loadable_mo(tmp_path):
    catalog_dir = tmp_path / "locale" / "ru" / "LC_MESSAGES"
    catalog_dir.mkdir(parents=True)
    po = catalog_dir / "blindrss.po"
    po.write_text(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
        "\n"
        'msgid "All Articles"\n'
        'msgstr "Все статьи"\n'
        "\n"
        'msgid "{count} item"\n'
        'msgid_plural "{count} items"\n'
        'msgstr[0] "{count} элемент"\n'
        'msgstr[1] "{count} элементов"\n',
        encoding="utf-8",
    )

    mo = compile_translations.compile_catalog(po)

    with mo.open("rb") as fh:
        translations = gettext.GNUTranslations(fh)
    assert translations.gettext("All Articles") == "Все статьи"
    assert translations.ngettext("{count} item", "{count} items", 2) == "{count} элементов"


def test_iter_catalogs_finds_blindrss_po_only(tmp_path):
    good = tmp_path / "ru" / "LC_MESSAGES" / "blindrss.po"
    good.parent.mkdir(parents=True)
    good.write_text('msgid ""\nmsgstr ""\n', encoding="utf-8")
    other = tmp_path / "ru" / "LC_MESSAGES" / "other.po"
    other.write_text('msgid ""\nmsgstr ""\n', encoding="utf-8")

    assert compile_translations.iter_catalogs(tmp_path) == [good]


def test_blank_and_incomplete_translations_fall_back_to_english(tmp_path):
    catalog_dir = tmp_path / "locale" / "xx" / "LC_MESSAGES"
    catalog_dir.mkdir(parents=True)
    po = catalog_dir / "blindrss.po"
    po.write_text(
        'msgid ""\n'
        'msgstr ""\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Plural-Forms: nplurals=2; plural=(n != 1);\\n"\n'
        "\n"
        'msgid "Ambiguous short label"\n'
        'msgstr ""\n'
        "\n"
        'msgid "{count} item"\n'
        'msgid_plural "{count} items"\n'
        'msgstr[0] "{count} translated item"\n'
        'msgstr[1] ""\n'
        "\n"
        'msgid "{count} missing form"\n'
        'msgid_plural "{count} missing forms"\n'
        'msgstr[0] "{count} translated form"\n',
        encoding="utf-8",
    )

    mo = compile_translations.compile_catalog(po)

    with mo.open("rb") as fh:
        translations = gettext.GNUTranslations(fh)
    assert translations.gettext("Ambiguous short label") == "Ambiguous short label"
    assert translations.ngettext("{count} item", "{count} items", 1) == "{count} item"
    assert translations.ngettext("{count} item", "{count} items", 2) == "{count} items"
    assert translations.ngettext(
        "{count} missing form", "{count} missing forms", 1
    ) == "{count} missing form"
    assert translations.ngettext(
        "{count} missing form", "{count} missing forms", 2
    ) == "{count} missing forms"


def test_repository_russian_catalog_has_readable_cyrillic():
    catalog = Path("locale/ru/LC_MESSAGES/blindrss.po")
    messages = compile_translations.read_po(catalog)

    assert messages["All Articles"] == "Все статьи"
    assert "Ð" not in messages["All Articles"]


def test_repository_russian_catalog_preserves_named_placeholders():
    messages = compile_translations.read_po(
        Path("locale/ru/LC_MESSAGES/blindrss.po")
    )

    def fields(value):
        return {
            field_name
            for _literal, field_name, _format_spec, _conversion
            in Formatter().parse(value)
            if field_name is not None
        }

    for raw_msgid, translated in messages.items():
        if not raw_msgid:
            continue
        if "\0" not in raw_msgid:
            assert fields(translated) == fields(raw_msgid), raw_msgid
            continue
        singular, plural = raw_msgid.split("\0", 1)
        translated_forms = translated.split("\0")
        for index, translated_form in enumerate(translated_forms):
            source_form = singular if index == 0 else plural
            assert fields(translated_form) == fields(source_form), raw_msgid
