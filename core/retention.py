# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Language-independent retention settings (issue #63).

Config stores stable identifiers such as ``"1_week"`` or ``"unlimited"``; the
UI maps them to localized labels at display time. Internal logic (cleanup,
seconds/day math) must only ever see identifiers, never display labels —
older configs stored the English combobox label verbatim, which broke as soon
as those labels became translatable.
"""

from core.i18n import _

# Ordered (identifier, days) pairs offered in the Settings comboboxes.
# ``None`` days means keep forever.
RETENTION_CHOICES = (
    ("1_day", 1),
    ("3_days", 3),
    ("1_week", 7),
    ("2_weeks", 14),
    ("3_weeks", 21),
    ("1_month", 30),
    ("2_months", 60),
    ("6_months", 180),
    ("1_year", 365),
    ("2_years", 730),
    ("5_years", 1825),
    ("unlimited", None),
)

RETENTION_DEFAULT = "unlimited"

# Identifiers still honored from old configs but no longer offered in the UI
# (early builds' cleanup logic accepted these labels).
_HIDDEN_DAYS = {"2_days": 2, "3_months": 90}

_DAYS_BY_ID = {ident: days for ident, days in RETENTION_CHOICES}
_DAYS_BY_ID.update(_HIDDEN_DAYS)

# Configs written before v1.100 stored the English UI label verbatim.
_LEGACY_LABELS = {
    "1 day": "1_day",
    "2 days": "2_days",
    "3 days": "3_days",
    "1 week": "1_week",
    "2 weeks": "2_weeks",
    "3 weeks": "3_weeks",
    "1 month": "1_month",
    "2 months": "2_months",
    "3 months": "3_months",
    "6 months": "6_months",
    "1 year": "1_year",
    "2 years": "2_years",
    "5 years": "5_years",
    "unlimited": "unlimited",
}


def normalize_retention(value) -> str:
    """Map a stored config value (identifier or legacy label) to an identifier.

    Unknown values fall back to ``RETENTION_DEFAULT`` (keep forever) — the
    safe direction: never delete more than the user asked for.
    """
    text = str(value or "").strip()
    if text in _DAYS_BY_ID:
        return text
    legacy = _LEGACY_LABELS.get(text.lower())
    if legacy:
        return legacy
    return RETENTION_DEFAULT


def retention_days(value):
    """Days to keep for a stored value, or ``None`` for unlimited/unknown."""
    return _DAYS_BY_ID.get(normalize_retention(value))


def retention_seconds(value):
    """Seconds to keep for a stored value, or ``None`` for unlimited/unknown."""
    days = retention_days(value)
    return None if days is None else days * 86400


def retention_label(ident: str) -> str:
    """Localized display label for a retention identifier.

    Called at display time so the active gettext catalog applies. The msgid
    literals below are what tools/extract_strings.py collects into the POT.
    """
    labels = {
        "1_day": _("1 day"),
        "2_days": _("2 days"),
        "3_days": _("3 days"),
        "1_week": _("1 week"),
        "2_weeks": _("2 weeks"),
        "3_weeks": _("3 weeks"),
        "1_month": _("1 month"),
        "2_months": _("2 months"),
        "3_months": _("3 months"),
        "6_months": _("6 months"),
        "1_year": _("1 year"),
        "2_years": _("2 years"),
        "5_years": _("5 years"),
        "unlimited": _("Unlimited"),
    }
    return labels.get(normalize_retention(ident), _("Unlimited"))
