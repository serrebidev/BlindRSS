# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""The browser identity BlindRSS presents on outbound HTTP requests.

A stale User-Agent is a bot signal by itself. `core.utils.HEADERS` used to carry
a hard-coded Chrome/124 string that aged out of every WAF's "current browser"
window, so sites behind a Cloudflare managed challenge (forum.audiogames.net)
answered "Just a moment..." to every request the app made, and full-text
extraction had nothing to fall back on.

Three things keep the identity current:

* **Automatic** (the default) reads the versions of the browsers actually
  installed on this machine, so the app claims to be a browser the user really
  has, at the version they really run.
* The **baked presets** below are refreshed at release time by
  `tools/refresh_user_agents.py` from the build machine's browsers, so a user
  with no detectable browser still gets a recent string.
* The user can pick a specific preset or type their own (Settings > Advanced).

A User-Agent never travels alone: Chromium sends `sec-ch-ua*` client hints that
must agree with it, and Firefox sends none at all. Claiming Firefox while
sending Chromium hints is a *worse* fingerprint than the stale string it
replaced, so presets own their hint headers and `apply_to_headers` strips the
ones that do not belong.
"""

from __future__ import annotations

import logging
import os
import plistlib
import re
import subprocess
import sys
import threading

from core.i18n import _

log = logging.getLogger(__name__)


# --- Baked-in versions -----------------------------------------------------
# Refreshed at release time from the build machine (tools/refresh_user_agents.py).
# Chromium majors move together across Chrome/Edge/Brave, so one number covers
# all three; Gecko tracks its own.
# BEGIN GENERATED VERSIONS
CHROMIUM_MAJOR = "151"
FIREFOX_MAJOR = "153"
# END GENERATED VERSIONS


_UA_TEMPLATES = {
    ("chromium", "windows"): (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    ),
    ("chromium", "macos"): (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    ),
    ("chromium", "linux"): (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36"
    ),
    ("edge", "windows"): (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
    ),
    ("edge", "macos"): (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
    ),
    ("edge", "linux"): (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/{v}.0.0.0 Safari/537.36 Edg/{v}.0.0.0"
    ),
    ("firefox", "windows"): (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:{v}.0) Gecko/20100101 Firefox/{v}.0"
    ),
    ("firefox", "macos"): (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:{v}.0) Gecko/20100101 Firefox/{v}.0"
    ),
    ("firefox", "linux"): (
        "Mozilla/5.0 (X11; Linux x86_64; rv:{v}.0) Gecko/20100101 Firefox/{v}.0"
    ),
}

# Client-hint brand lists. Chrome and Brave are indistinguishable here on
# purpose: Brave ships Chrome's UA and Chrome's brands so it does not stand out.
_CH_BRANDS = {
    "chromium": '"Chromium";v="{v}", "Google Chrome";v="{v}", "Not-A.Brand";v="99"',
    "edge": '"Chromium";v="{v}", "Microsoft Edge";v="{v}", "Not-A.Brand";v="99"',
}

_CH_PLATFORM = {"windows": '"Windows"', "macos": '"macOS"', "linux": '"Linux"'}

# Every client-hint header this module owns. apply_to_headers removes all of
# them before adding back the ones the chosen identity actually sends, so
# switching Chrome -> Firefox cannot leave a Chromium hint behind.
CLIENT_HINT_HEADERS = ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")


def _platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def build_ua(engine: str, platform_key: str, major: str) -> str:
    """The UA string for an engine/platform/major triple, or "" if unknown."""
    template = _UA_TEMPLATES.get((engine, platform_key))
    if not template or not str(major or "").strip():
        return ""
    return template.format(v=str(major).strip())


def client_hints_for(engine: str, platform_key: str, major: str) -> dict:
    """The `sec-ch-ua*` headers that accompany a UA. Empty for Gecko."""
    brands = _CH_BRANDS.get(engine)
    if not brands:
        return {}
    return {
        "sec-ch-ua": brands.format(v=str(major).strip()),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": _CH_PLATFORM.get(platform_key, '"Windows"'),
    }


# --- Built-in presets ------------------------------------------------------
# (key, label, engine, platform, major-getter). Labels are display-only; keys
# are persisted in config and must never change.
_PRESET_SPECS = (
    ("chrome_windows", "Google Chrome (Windows)", "chromium", "windows", "chromium"),
    ("chrome_macos", "Google Chrome (macOS)", "chromium", "macos", "chromium"),
    ("chrome_linux", "Google Chrome (Linux)", "chromium", "linux", "chromium"),
    ("edge_windows", "Microsoft Edge (Windows)", "edge", "windows", "chromium"),
    ("edge_macos", "Microsoft Edge (macOS)", "edge", "macos", "chromium"),
    ("firefox_windows", "Mozilla Firefox (Windows)", "firefox", "windows", "firefox"),
    ("firefox_macos", "Mozilla Firefox (macOS)", "firefox", "macos", "firefox"),
    ("firefox_linux", "Mozilla Firefox (Linux)", "firefox", "linux", "firefox"),
)

AUTO_MODE = "auto"
CUSTOM_MODE = "custom"
INSTALLED_PREFIX = "installed:"

# The preset used when detection finds nothing and no choice was made.
_FALLBACK_PRESET = "chrome_windows"


class Identity:
    """A resolved browser identity: the UA plus the hints that go with it."""

    def __init__(self, key: str, label: str, ua: str, hints: dict, source: str = ""):
        self.key = key
        self.label = label
        self.ua = ua
        self.hints = dict(hints or {})
        # "preset" | "installed" | "custom" — display only.
        self.source = source

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<Identity {self.key} {self.ua!r}>"


def presets() -> list:
    """Every built-in identity, in menu order."""
    out = []
    for key, label, engine, plat, series in _PRESET_SPECS:
        major = CHROMIUM_MAJOR if series == "chromium" else FIREFOX_MAJOR
        ua = build_ua(engine, plat, major)
        if not ua:
            continue
        out.append(Identity(key, label, ua, client_hints_for(engine, plat, major), "preset"))
    return out


def preset_by_key(key: str):
    for identity in presets():
        if identity.key == key:
            return identity
    return None


# --- Detecting the browsers installed on this machine ----------------------

_detect_lock = threading.Lock()
_detect_cache = None

# Chromium keeps a versioned folder beside its executable
# (`Application\150.0.4078.83\`), which is the cheapest reliable version source
# and needs no registry access or process launch.
_CHROMIUM_VERSION_DIR_RE = re.compile(r"^(\d+)\.\d+\.\d+\.\d+$")

# Pre-release channels are listed after their stable sibling and only used when
# stable is absent, so a machine with both is identified as the stable build
# most of the web is running. Each browser resolves to one entry.
_WINDOWS_CHROMIUM_BROWSERS = (
    ("brave", "Brave", "chromium", (
        r"BraveSoftware\Brave-Browser\Application",
        r"BraveSoftware\Brave-Browser-Beta\Application",
        r"BraveSoftware\Brave-Browser-Nightly\Application",
    )),
    ("chrome", "Google Chrome", "chromium", (
        r"Google\Chrome\Application",
        r"Google\Chrome Beta\Application",
        r"Google\Chrome Dev\Application",
    )),
    ("edge", "Microsoft Edge", "edge", (
        r"Microsoft\Edge\Application",
        r"Microsoft\Edge Beta\Application",
        r"Microsoft\Edge Dev\Application",
    )),
)

_MACOS_BROWSERS = (
    ("brave", "Brave", "chromium", "/Applications/Brave Browser.app"),
    ("chrome", "Google Chrome", "chromium", "/Applications/Google Chrome.app"),
    ("edge", "Microsoft Edge", "edge", "/Applications/Microsoft Edge.app"),
    ("firefox", "Mozilla Firefox", "firefox", "/Applications/Firefox.app"),
)

_LINUX_BROWSERS = (
    ("brave", "Brave", "chromium", ("brave-browser", "brave")),
    ("chrome", "Google Chrome", "chromium", ("google-chrome", "google-chrome-stable")),
    ("edge", "Microsoft Edge", "edge", ("microsoft-edge", "microsoft-edge-stable")),
    ("firefox", "Mozilla Firefox", "firefox", ("firefox",)),
)


def _program_roots() -> list:
    roots = []
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        value = os.environ.get(var, "")
        if value and value not in roots:
            roots.append(value)
    return roots


def _chromium_major_from_dir(app_dir: str) -> str:
    """Highest versioned subdirectory major under a Chromium `Application` dir."""
    best = 0
    try:
        entries = os.listdir(app_dir)
    except OSError:
        return ""
    for name in entries:
        match = _CHROMIUM_VERSION_DIR_RE.match(name)
        if not match:
            continue
        if not os.path.isdir(os.path.join(app_dir, name)):
            continue
        best = max(best, int(match.group(1)))
    return str(best) if best else ""


def _firefox_major_from_install(install_dir: str) -> str:
    """Firefox records its version in `application.ini` beside the executable."""
    path = os.path.join(install_dir, "application.ini")
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.lower().startswith("version="):
                    major = line.split("=", 1)[1].strip().split(".", 1)[0]
                    return major if major.isdigit() else ""
    except OSError:
        return ""
    return ""


def _detect_windows() -> list:
    found = []
    for browser_key, label, engine, rels in _WINDOWS_CHROMIUM_BROWSERS:
        major = ""
        # Channels in preference order; roots inside, since a browser may be
        # installed per-user in one channel and per-machine in another.
        for rel in rels:
            for root in _program_roots():
                major = _chromium_major_from_dir(os.path.join(root, rel))
                if major:
                    break
            if major:
                break
        if major:
            found.append((browser_key, label, engine, major))
    for root in _program_roots():
        for rel in ("Mozilla Firefox", r"Mozilla\Firefox"):
            major = _firefox_major_from_install(os.path.join(root, rel))
            if major:
                found.append(("firefox", "Mozilla Firefox", "firefox", major))
                break
        else:
            continue
        break
    return found


def _macos_bundle_major(app_path: str) -> str:
    path = os.path.join(app_path, "Contents", "Info.plist")
    try:
        with open(path, "rb") as fh:
            data = plistlib.load(fh)
    except Exception:
        return ""
    version = str(data.get("CFBundleShortVersionString", "") or "")
    major = version.split(".", 1)[0].strip()
    return major if major.isdigit() else ""


def _detect_macos() -> list:
    found = []
    for browser_key, label, engine, app_path in _MACOS_BROWSERS:
        major = _macos_bundle_major(app_path)
        if major:
            found.append((browser_key, label, engine, major))
    return found


_LINUX_VERSION_RE = re.compile(r"(\d+)\.\d+")


def _detect_linux() -> list:
    found = []
    for browser_key, label, engine, commands in _LINUX_BROWSERS:
        for command in commands:
            try:
                proc = subprocess.run(
                    [command, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.SubprocessError):
                continue
            match = _LINUX_VERSION_RE.search(proc.stdout or "")
            if match:
                found.append((browser_key, label, engine, match.group(1)))
                break
    return found


def detect_installed(*, refresh: bool = False) -> list:
    """Identities for the browsers installed on this machine, newest engine first.

    Cached for the process: this touches the filesystem (and, on Linux, launches
    `--version`), and installed browsers do not change mid-session.
    """
    global _detect_cache
    with _detect_lock:
        if _detect_cache is not None and not refresh:
            return list(_detect_cache)
    try:
        if sys.platform.startswith("win"):
            raw = _detect_windows()
        elif sys.platform == "darwin":
            raw = _detect_macos()
        else:
            raw = _detect_linux()
    except Exception:
        log.debug("Browser detection failed", exc_info=True)
        raw = []

    plat = _platform_key()
    out = []
    for browser_key, label, engine, major in raw:
        ua = build_ua(engine, plat, major)
        if not ua:
            continue
        out.append(
            Identity(
                INSTALLED_PREFIX + browser_key,
                _("{label} {major} (installed)").format(label=label, major=major),
                ua,
                client_hints_for(engine, plat, major),
                "installed",
            )
        )
    with _detect_lock:
        _detect_cache = list(out)
    return list(out)


def _installed_rank(identity) -> tuple:
    """Sort key for automatic selection: newest Chromium wins, Gecko last.

    Chromium is preferred because its client hints make the fingerprint richer
    and more ordinary; Firefox is a fine identity but a rarer one.
    """
    major = 0
    match = re.search(r"(?:Chrome|Firefox)/(\d+)", identity.ua)
    if match:
        major = int(match.group(1))
    is_gecko = "Firefox/" in identity.ua
    return (0 if not is_gecko else 1, -major)


def automatic_identity():
    """The best installed browser, or the baked preset when none is detected."""
    installed = sorted(detect_installed(), key=_installed_rank)
    if installed:
        return installed[0]
    plat = _platform_key()
    for identity in presets():
        if identity.key.endswith("_" + plat):
            return identity
    return preset_by_key(_FALLBACK_PRESET)


# --- Custom strings --------------------------------------------------------

# curl_cffi impersonation targets by engine. A clearance cookie is validated
# against the TLS/HTTP handshake as well as the UA, so a Firefox cookie sent
# over Chrome's hello (or plain requests') is rejected — measured against
# forum.audiogames.net, where the same cookie 403'd on `requests` and on
# `chrome`, and returned the article on `firefox`.
_CURL_TARGET_BY_ENGINE = {
    "firefox": "firefox",
    "chromium": "chrome",
    "edge": "chrome",
}


def impersonate_target_for_ua(ua: str) -> str:
    """The curl_cffi target whose handshake matches `ua`, or "" if unknown."""
    ua = str(ua or "")
    if "Firefox/" in ua or "Gecko/" in ua:
        return _CURL_TARGET_BY_ENGINE["firefox"]
    if "Edg/" in ua or "Edge/" in ua:
        return _CURL_TARGET_BY_ENGINE["edge"]
    if "Chrome/" in ua or "Chromium/" in ua:
        return _CURL_TARGET_BY_ENGINE["chromium"]
    return ""


def identity_from_string(ua: str):
    """Wrap a user-typed UA, inferring the client hints it should travel with.

    Sniffing rather than asking: a hand-written Firefox string paired with
    Chromium hints is exactly the inconsistency this module exists to prevent.
    """
    ua = str(ua or "").strip()
    if not ua:
        return None
    if "Firefox/" in ua or "Gecko/" in ua:
        engine = "firefox"
    elif "Edg/" in ua or "Edge/" in ua:
        engine = "edge"
    elif "Chrome/" in ua or "Chromium/" in ua:
        engine = "chromium"
    else:
        # Safari, a bespoke string, or a deliberate non-browser identity: send
        # it verbatim with no hints rather than inventing a brand list for it.
        engine = ""

    if "Windows" in ua:
        plat = "windows"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        plat = "macos"
    else:
        plat = "linux"

    major = ""
    match = re.search(r"(?:Chrome|Firefox|Edg)/(\d+)", ua)
    if match:
        major = match.group(1)

    hints = client_hints_for(engine, plat, major) if (engine and major) else {}
    return Identity(CUSTOM_MODE, "Custom", ua, hints, "custom")


# --- Config resolution -----------------------------------------------------

def choices() -> list:
    """Every selectable identity, in menu order: Automatic, installed, presets.

    The Automatic entry is rebuilt on each call so its label always names the
    browser it currently resolves to.
    """
    auto = automatic_identity()
    auto_label = _("Automatic ({label})").format(label=auto.label) if auto else _("Automatic")
    out = [Identity(AUTO_MODE, auto_label, auto.ua if auto else "", auto.hints if auto else {}, "auto")]
    out.extend(detect_installed())
    out.extend(presets())
    return out


def resolve(config_get):
    """The identity the app should present, from config. Never returns None."""
    try:
        mode = str(config_get("user_agent_mode", AUTO_MODE) or AUTO_MODE).strip()
    except Exception:
        mode = AUTO_MODE

    if mode == CUSTOM_MODE:
        try:
            custom = config_get("user_agent_custom", "")
        except Exception:
            custom = ""
        identity = identity_from_string(custom)
        if identity is not None:
            return identity
        mode = AUTO_MODE

    if mode and mode != AUTO_MODE:
        for identity in detect_installed():
            if identity.key == mode:
                return identity
        identity = preset_by_key(mode)
        if identity is not None:
            return identity
        # A key from a newer build, or an uninstalled browser: fall through to
        # Automatic rather than shipping an empty User-Agent.

    return automatic_identity() or preset_by_key(_FALLBACK_PRESET)


def apply_to_headers(config_get, headers: dict | None = None) -> str:
    """Point `core.utils.HEADERS` at the configured identity. Returns the UA.

    Mutates in place because callers all over the app hold references taken at
    import time (`from core.utils import HEADERS`) or copy the dict per request.
    """
    if headers is None:
        from core import utils

        headers = utils.HEADERS
    identity = resolve(config_get)
    if identity is None or not identity.ua:
        return str(headers.get("User-Agent", ""))
    headers["User-Agent"] = identity.ua
    for name in CLIENT_HINT_HEADERS:
        headers.pop(name, None)
    headers.update(identity.hints)
    return identity.ua
