# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Interface internationalization via gettext (issue #44).

English source strings are the message keys (gettext convention), so with no
translation catalog installed every ``_()`` call returns its argument and the
app behaves exactly as before. Translations live in
``locale/<lang>/LC_MESSAGES/blindrss.mo``; ``tools/extract_strings.py``
regenerates the ``blindrss.pot`` template translators start from.

Usage in application code::

    from core.i18n import _
    label = _("All Articles")

``setup()`` must run before GUI modules build their menus/labels (main.py does
this right after loading config). The selected language comes from the
``"language"`` config key: ``"auto"`` (default) follows the OS locale, any
other value is a language code such as ``"ru"`` or ``"pt_BR"``.
"""

import gettext
import locale
import logging
import os
import sys

log = logging.getLogger(__name__)

DOMAIN = "blindrss"

_translation = gettext.NullTranslations()

# BCP-47 code of the catalog currently installed; see current_language().
_active_language = "en"


def locale_dir() -> str:
    """Directory holding <lang>/LC_MESSAGES/blindrss.mo, source tree or frozen."""
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "locale")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "locale")


def override_locale_dir() -> str:
    """Writable locale tree holding catalogs downloaded after release.

    The bundled tree is inside the read-only PyInstaller payload and is rebuilt
    on every launch, so over-the-air translations live beside config.json
    instead (see core.translation_updates).
    """
    try:
        from core.translation_updates import (
            override_root,
            prepare_overrides_for_app_version,
        )

        prepare_overrides_for_app_version()
        return override_root()
    except Exception:
        return ""


def catalog_dirs() -> list:
    """Directories to search for catalogs, most preferred first.

    Downloaded catalogs win over bundled ones within one app version. On an app
    version change, override_locale_dir() first removes them so an older
    downloaded snapshot cannot shadow the new release's bundled catalog.
    """
    dirs = []
    override = override_locale_dir()
    if override:
        dirs.append(override)
    dirs.append(locale_dir())
    return dirs


def _system_languages() -> list:
    languages = []
    for env_key in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(env_key)
        if value:
            languages.extend(part for part in value.split(":") if part)
            break
    try:
        system_locale = locale.getlocale()[0]
        if system_locale:
            languages.append(system_locale)
    except Exception:
        pass
    if sys.platform == "win32":
        try:
            import ctypes

            # Note: do not name this local "windll" -- PyInstaller's ctypes
            # bytecode scanner treats `windll.X` as loading "X.dll" and warns
            # "Library GetUserDefaultUILanguage.dll required via ctypes not
            # found" at build time.
            kernel32 = ctypes.windll.kernel32
            lcid = kernel32.GetUserDefaultUILanguage()
            name = locale.windows_locale.get(lcid)
            if name:
                languages.append(name)
        except Exception:
            pass
    return languages


def setup(language: str = "auto") -> None:
    """Install the translation catalog for ``language`` ("auto" = OS locale)."""
    global _translation
    language = str(language or "auto").strip()
    if language.lower() in ("", "auto"):
        languages = _system_languages()
    else:
        languages = [language]

    _translation = _load_catalog(languages)
    _remember_active_language(languages)


def _load_catalog(languages: list):
    """First catalog found across catalog_dirs(), else an identity fallback."""
    for directory in catalog_dirs():
        if not directory:
            continue
        try:
            # fallback=False so a miss here falls through to the next directory
            # instead of stopping the search with a NullTranslations.
            return gettext.translation(
                DOMAIN, localedir=directory, languages=languages, fallback=False
            )
        except OSError:
            continue
        except Exception:
            log.debug("Failed to load translations from %s", directory, exc_info=True)
            continue
    return gettext.NullTranslations()


def _remember_active_language(languages: list) -> None:
    """Record the catalog language that actually loaded (see current_language)."""
    global _active_language
    resolved = ""
    # A real catalog reports its own language; NullTranslations (no catalog for
    # any requested language) has no info(), which is itself the answer: the
    # untranslated English source strings are what the user sees.
    try:
        info = _translation.info()
        resolved = str(info.get("language") or "").strip()
    except Exception:
        resolved = ""
    if not resolved:
        resolved = "en" if isinstance(_translation, gettext.NullTranslations) else ""
    if not resolved:
        resolved = str(languages[0]) if languages else "en"
    _active_language = resolved.replace("_", "-")


def current_language() -> str:
    """BCP-47 code of the UI language in effect (e.g. "ru", "pt-BR", "en").

    This is what the app is actually speaking, not what was requested: "auto"
    resolves to the OS locale, and a language with no catalog resolves to "en"
    because English source strings are the fallback. Used as the document
    language for the rich reader (issue #72) -- assistive tech needs to know
    which synthesizer and Braille table to use.
    """
    return _active_language or "en"


def _(message: str) -> str:
    """Translate ``message`` using the installed catalog (identity fallback)."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Plural-aware translation (identity English fallback)."""
    return _translation.ngettext(singular, plural, n)


def available_languages() -> list:
    """Language codes that have a compiled catalog on disk (for Settings)."""
    found = []
    for base in catalog_dirs():
        if not base:
            continue
        try:
            for entry in sorted(os.listdir(base)):
                mo = os.path.join(base, entry, "LC_MESSAGES", DOMAIN + ".mo")
                if os.path.isfile(mo) and entry not in found:
                    found.append(entry)
        except OSError:
            continue
    return sorted(found)
