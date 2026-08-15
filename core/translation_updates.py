# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Over-the-air UI translation updates.

Translations change far more often than the app does: a translator PR lands and,
without this, every user waits for the next release to see it. This module
fetches the .po catalogs straight from the repository and compiles them into a
writable override directory that core.i18n prefers over the bundled ones, so a
translation fix reaches users with no new build.

Design notes:

- Source of truth is the repo's ``main`` branch, which is what releases are cut
  from, so a downloaded catalog is never older than the bundled one.
- Only compiled .mo files ship in the PyInstaller bundle, so the .po text is
  compiled locally (core.po_compile) rather than downloaded pre-compiled.
- Freshness uses HTTP ETags against raw.githubusercontent.com: an unchanged
  catalog costs one conditional request answered with 304 and no body. That
  keeps even a ten-minute check cheap and avoids the GitHub API's 60/hour
  anonymous limit.
- A newly installed app version discards downloaded overrides before gettext
  starts. The new release's bundled catalogs are authoritative until a later
  check downloads an equal or newer catalog from ``main``.
- Catalogs are written atomically via a temp file and only after they parse into
  a non-empty message map, so an interrupted or truncated download can never
  leave a broken catalog that would blank the whole UI.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from core import po_compile
from core.update_config import GITHUB_OWNER, GITHUB_REPO

log = logging.getLogger(__name__)

BRANCH = "main"
DOMAIN = "blindrss"
STATE_FILENAME = "translation_updates.json"

CATALOG_URL = (
    "https://raw.githubusercontent.com/"
    f"{GITHUB_OWNER}/{GITHUB_REPO}/{BRANCH}/locale/{{lang}}/LC_MESSAGES/{DOMAIN}.po"
)

# Config keys (defaults live here so GUI and scheduler agree).
CFG_ENABLED = "translation_auto_update"
CFG_FREQUENCY = "translation_update_frequency"
CFG_LAST_CHECK = "translation_update_last_check"

DEFAULT_ENABLED = True
DEFAULT_FREQUENCY = "daily"

FREQUENCY_SECONDS = {
    "startup": 0,
    "ten_minutes": 10 * 60,
    "daily": 24 * 60 * 60,
    "weekly": 7 * 24 * 60 * 60,
    "monthly": 30 * 24 * 60 * 60,
}

# Re-evaluate the setting at the shortest supported interval. This is separate
# from the selected update frequency: it lets a long-running process notice
# when an interval becomes due or when Settings enables/changes the feature.
AUTO_UPDATE_POLL_SECONDS = FREQUENCY_SECONDS["ten_minutes"]

# A catalog that parses to fewer than this many messages is treated as damaged
# rather than installed; the real catalogs carry >1000 entries.
MIN_SANE_MESSAGES = 50

# Avoid repeated state-file reads through i18n.catalog_dirs() during one
# process. Tests reset this when exercising version transitions.
_prepared_app_version = ""


@dataclass
class UpdateResult:
    """Outcome of one check. ``updated`` lists language codes actually changed."""

    updated: list = field(default_factory=list)
    checked: list = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def changed(self) -> bool:
        return bool(self.updated)


def override_root() -> str:
    """Writable locale tree that shadows the bundled catalogs."""
    from core.config import get_data_dir

    return os.path.join(get_data_dir(), "locale")


def _state_path() -> str:
    from core.config import get_data_dir

    return os.path.join(get_data_dir(), STATE_FILENAME)


def load_state() -> dict:
    import json

    try:
        with open(_state_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: dict) -> None:
    import json

    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=1)
    except Exception:
        log.debug("Could not save translation update state", exc_info=True)


def catalog_path(language: str) -> str:
    return os.path.join(override_root(), language, "LC_MESSAGES", DOMAIN + ".mo")


def prepare_overrides_for_app_version(app_version: str | None = None) -> bool:
    """Make bundled catalogs authoritative after installing a new app version.

    Downloaded catalogs are snapshots of ``main`` at their check time. They can
    therefore be older than the catalogs in a later BlindRSS release, despite
    coming from the same branch. Remove them once per version before gettext
    chooses a catalog, clear their ETags, and make the first background check
    due immediately. Returns True when a version transition was handled.
    """
    global _prepared_app_version

    if app_version is None:
        from core.version import APP_VERSION

        app_version = APP_VERSION
    current = str(app_version or "").strip()
    if not current or _prepared_app_version == current:
        return False

    state = load_state()
    recorded = str(state.get("app_version") or "").strip()
    if recorded == current:
        _prepared_app_version = current
        return False

    root = override_root()
    try:
        if os.path.exists(root):
            shutil.rmtree(root)
    except Exception:
        # Do not record the new version if cleanup failed; retry next launch so
        # an old override cannot be accepted permanently. The caller in i18n
        # falls back to the bundled tree when this exception escapes.
        log.warning("Could not remove stale translation overrides", exc_info=True)
        raise

    state["app_version"] = current
    state.pop("etags", None)
    state.pop("last_check", None)
    save_state(state)
    _prepared_app_version = current
    if recorded:
        log.info(
            "Reset translation overrides after app update %s -> %s",
            recorded,
            current,
        )
    return True


def installed_languages() -> list:
    """Languages that already have a downloaded override catalog."""
    found = []
    try:
        root = override_root()
        for entry in sorted(os.listdir(root)):
            if os.path.isfile(os.path.join(root, entry, "LC_MESSAGES", DOMAIN + ".mo")):
                found.append(entry)
    except OSError:
        pass
    return found


def _install_catalog(language: str, po_text: str) -> bool:
    """Compile and atomically install one catalog. False if it looks damaged."""
    messages = po_compile.parse_po_text(po_text)
    if len(messages) < MIN_SANE_MESSAGES:
        log.warning(
            "Refusing translation update for %s: only %d messages parsed",
            language,
            len(messages),
        )
        return False

    dest = Path(catalog_path(language))
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".mo", dir=str(dest.parent))
    os.close(tmp_fd)
    try:
        po_compile.write_mo(messages, Path(tmp_name))
        # os.replace is atomic on both POSIX and Windows: readers see either the
        # old catalog or the new one, never a half-written file.
        os.replace(tmp_name, str(dest))
        return True
    except Exception:
        try:
            os.unlink(tmp_name)
        except Exception:
            pass
        raise


def _fetch_catalog(language: str, etag: str, timeout: int):
    """Return (status, po_text, etag). status is 'updated' | 'unchanged' | 'missing'."""
    from core.utils import safe_requests_get

    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    resp = safe_requests_get(CATALOG_URL.format(lang=language), headers=headers, timeout=timeout)

    if resp.status_code == 304:
        return "unchanged", "", etag
    if resp.status_code == 404:
        # Language has no catalog upstream (e.g. a locale we do not ship).
        return "missing", "", ""
    resp.raise_for_status()

    text = resp.text or ""
    # requests guesses latin-1 for text/plain without a charset; PO files are
    # UTF-8 by definition and non-ASCII translations would arrive mangled.
    if resp.encoding and resp.encoding.lower() not in ("utf-8", "utf8"):
        try:
            text = resp.content.decode("utf-8")
        except Exception:
            pass
    return "updated", text, str(resp.headers.get("ETag") or "")


def check_and_update(languages, force: bool = False, timeout: int = 20) -> UpdateResult:
    """Fetch and install newer catalogs for ``languages``.

    Network and disk work only; callers run this off the UI thread. Never
    raises: transport problems are reported through ``UpdateResult.error``.
    """
    result = UpdateResult()
    wanted = [str(code).strip() for code in (languages or []) if str(code or "").strip()]
    # English is the msgid source; there is no catalog to fetch for it.
    wanted = [code for code in dict.fromkeys(wanted) if code.lower() not in ("en", "c", "posix")]
    if not wanted:
        return result

    state = load_state()
    etags = state.get("etags") or {}
    if not isinstance(etags, dict):
        etags = {}
    errors = []

    for language in wanted:
        result.checked.append(language)
        etag = "" if force else str(etags.get(language) or "")
        # An override recorded in state but missing on disk must be re-fetched
        # even when the ETag says "unchanged".
        if etag and not os.path.isfile(catalog_path(language)):
            etag = ""
        try:
            status, po_text, new_etag = _fetch_catalog(language, etag, timeout)
        except Exception as exc:
            log.debug("Translation update failed for %s", language, exc_info=True)
            errors.append(str(exc))
            continue

        if status == "unchanged":
            continue
        if status == "missing":
            etags.pop(language, None)
            continue
        try:
            if _install_catalog(language, po_text):
                etags[language] = new_etag
                result.updated.append(language)
        except Exception as exc:
            log.debug("Installing catalog failed for %s", language, exc_info=True)
            errors.append(str(exc))

    state["etags"] = etags
    state["last_check"] = int(time.time())
    save_state(state)

    if errors and not result.updated:
        result.error = errors[0]
    return result


def last_check_time() -> int:
    try:
        return int(load_state().get("last_check") or 0)
    except Exception:
        return 0


def is_due(frequency: str, now: float | None = None) -> bool:
    """True when the configured interval since the last successful check elapsed."""
    interval = FREQUENCY_SECONDS.get(str(frequency or DEFAULT_FREQUENCY).lower())
    if interval is None:
        interval = FREQUENCY_SECONDS[DEFAULT_FREQUENCY]
    last = last_check_time()
    if not last:
        return True
    return (now if now is not None else time.time()) - last >= interval


def clear_overrides() -> None:
    """Remove every downloaded catalog (Settings' reset path)."""
    try:
        shutil.rmtree(override_root(), ignore_errors=True)
    except Exception:
        log.debug("Could not clear translation overrides", exc_info=True)
    state = load_state()
    state.pop("etags", None)
    save_state(state)
