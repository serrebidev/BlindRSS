# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Language resolution for the rich reader (issue #72).

The rich view marked every article ``lang="en"``, so a screen reader read
non-English content with an English voice and Braille table. These pin the
priority order and, importantly, the refusal to guess: a wrong lang is worse
than none, because it actively points assistive tech at the wrong synthesizer.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import article_lang as al


class TestNormalize:
    def test_accepts_plain_and_regional_tags(self):
        assert al.normalize_lang("ru") == "ru"
        assert al.normalize_lang("EN") == "en"
        assert al.normalize_lang("en-us") == "en-US"

    def test_normalizes_posix_and_gettext_spellings(self):
        # These are what turn up in feeds and gettext catalogs.
        assert al.normalize_lang("pt_BR") == "pt-BR"
        assert al.normalize_lang("ru_RU.UTF-8") == "ru-RU"
        assert al.normalize_lang("zh_TW.Big5@modifier") == "zh-TW"

    def test_canonicalizes_script_and_region_case(self):
        assert al.normalize_lang("zh-hant-tw") == "zh-Hant-TW"

    def test_rejects_junk_rather_than_guessing(self):
        for junk in (None, "", "   ", 42, [], "{{ lang }}", "-", "a",
                     "this is a sentence", "12"):
            assert al.normalize_lang(junk) is None

    def test_recovers_a_trailing_separator(self):
        # "en_" is malformed, but the language subtag is unambiguous, so
        # recovering "en" is safe -- this is not guessing.
        assert al.normalize_lang("en_") == "en"


class TestPageHtml:
    def test_reads_lang_from_the_html_tag(self):
        assert al.lang_from_page_html('<!DOCTYPE html><html lang="ru"><body>x') == "ru"

    def test_reads_xml_lang_and_single_quotes(self):
        assert al.lang_from_page_html("<html xml:lang='de'>") == "de"
        assert al.lang_from_page_html('<html xml:lang="pt-br">') == "pt-BR"

    def test_ignores_lang_on_other_elements(self):
        """Only the document element declares the page language; a lang on some
        inner widget must not be mistaken for it."""
        html = '<html><body><p lang="fr">bonjour</p></body></html>'
        assert al.lang_from_page_html(html) is None

    def test_tolerates_attributes_before_lang(self):
        html = '<html class="no-js" data-x="1" lang="el" dir="ltr">'
        assert al.lang_from_page_html(html) == "el"

    def test_missing_or_empty_is_none(self):
        assert al.lang_from_page_html("<html><body>x</body></html>") is None
        assert al.lang_from_page_html('<html lang="">x') is None
        assert al.lang_from_page_html("") is None
        assert al.lang_from_page_html(None) is None


class TestPriority:
    def test_translation_target_outranks_everything(self):
        assert al.resolve_content_language(
            translation_target="ru",
            page_lang="de",
            feed_item_lang="fr",
            feed_lang="it",
            fallback="es",
        ) == "ru"

    def test_page_language_outranks_the_feed(self):
        assert al.resolve_content_language(
            page_lang="de", feed_item_lang="fr", feed_lang="it"
        ) == "de"

    def test_page_html_is_read_when_no_explicit_page_lang(self):
        assert al.resolve_content_language(
            page_html='<html lang="he"><body>x', feed_lang="it"
        ) == "he"

    def test_feed_item_language_outranks_the_channel(self):
        assert al.resolve_content_language(feed_item_lang="fr", feed_lang="it") == "fr"

    def test_channel_language_used_when_item_has_none(self):
        assert al.resolve_content_language(feed_lang="it") == "it"

    def test_falls_back_through_unusable_values(self):
        """An unusable higher-priority source must not shadow a good lower one --
        it should fall through, not return None or the junk."""
        assert al.resolve_content_language(
            translation_target="", page_lang="unknown", feed_item_lang=None, feed_lang="ja"
        ) == "ja"

    def test_explicit_fallback_is_used_before_the_ui_language(self):
        assert al.resolve_content_language(fallback="sv") == "sv"

    def test_always_returns_a_usable_tag(self):
        """The document must be marked with something -- an unmarked document is
        the bug being fixed."""
        result = al.resolve_content_language()
        assert result
        assert al.normalize_lang(result) == result


class TestAppUiLanguage:
    def test_tracks_the_installed_catalog(self):
        from core import i18n

        i18n.setup("ru")
        try:
            assert al.app_ui_language() == "ru"
        finally:
            i18n.setup("en")

    def test_language_without_a_catalog_reports_english(self):
        """English source strings are the fallback, so that is what is actually
        on screen -- claiming the requested language would be a lie to the
        screen reader."""
        from core import i18n

        i18n.setup("zz")  # no such catalog
        try:
            assert al.app_ui_language() == "en"
        finally:
            i18n.setup("en")

    def test_regional_catalog_reports_a_full_tag(self):
        from core import i18n

        i18n.setup("pt_BR")
        try:
            assert al.app_ui_language() in ("pt-BR", "pt")
        finally:
            i18n.setup("en")
