# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import glob
import importlib.util
import os
import re
import sys
import warnings
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# Build-time warning hygiene (keep in sync with the audit note in main.spec):
# pydantic's V1 shim warns on Python >= 3.14 (pyatv still needs it). It fires
# while PyInstaller imports packages to scan them and is not fixable here.
_BUILD_WARNING_IGNORES = (
    "Core Pydantic V1 functionality",
)
for _msg in _BUILD_WARNING_IGNORES:
    warnings.filterwarnings("ignore", message=_msg, category=UserWarning)
# Isolated hook-scan subprocesses only see env-level filters (literal prefix
# matches). Build-time env only; nothing leaks into the frozen app.
_pythonwarnings = [f"ignore:{_msg}:UserWarning" for _msg in _BUILD_WARNING_IGNORES]
if os.environ.get("PYTHONWARNINGS"):
    _pythonwarnings.insert(0, os.environ["PYTHONWARNINGS"])
os.environ["PYTHONWARNINGS"] = ",".join(_pythonwarnings)


ROOT = Path(os.getcwd())
BIN_DIR = ROOT / "bin"
PLATFORM = sys.platform


def _read_app_version():
    """Read APP_VERSION from core/version.py without importing the app package.

    Keep in sync with main.spec.
    """
    try:
        text = (ROOT / "core" / "version.py").read_text(encoding="utf-8")
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
        if m:
            return m.group(1)
    except Exception:
        pass
    return os.environ.get("BLINDRSS_APP_VERSION", "0.0.0")


_app_version = _read_app_version()

# Windows screen readers (NVDA's app-version report, the JAWS equivalent) read
# the application name and version out of the exe's VERSIONINFO resource; with
# no resource they announce "Application unknown, version not detected". This
# spec also builds on Windows, so it stamps the same resource main.spec does.
# On macOS the equivalent lives in the BUNDLE Info.plist below; ELF binaries
# have no such resource, so Linux gets nothing to stamp.
_win_version_info = None
if PLATFORM.startswith("win"):
    from PyInstaller.utils.win32.versioninfo import (
        VSVersionInfo,
        FixedFileInfo,
        StringFileInfo,
        StringTable,
        StringStruct,
        VarFileInfo,
        VarStruct,
    )

    _nums = [int(x) for x in re.findall(r"\d+", _app_version)[:4]]
    while len(_nums) < 4:
        _nums.append(0)
    _vt = tuple(_nums[:4])
    _win_version_info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=_vt,
            prodvers=_vt,
            mask=0x3F,
            flags=0x0,
            OS=0x40004,
            fileType=0x1,
            subtype=0x0,
            date=(0, 0),
        ),
        kids=[
            StringFileInfo([
                StringTable('040904B0', [
                    StringStruct('CompanyName', 'Serrebi'),
                    StringStruct('FileDescription', 'BlindRSS'),
                    StringStruct('FileVersion', _app_version),
                    StringStruct('InternalName', 'BlindRSS'),
                    StringStruct('OriginalFilename', 'BlindRSS.exe'),
                    StringStruct('ProductName', 'BlindRSS'),
                    StringStruct('ProductVersion', _app_version),
                    StringStruct(
                        'LegalCopyright',
                        'Copyright (c) 2024-2026 serrebidev and contributors',
                    ),
                ]),
            ]),
            VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])]),
        ],
    )

# Keep in sync with main.spec (see the audit note there): direct imports plus
# installed transitive deps whose data files collect_all protects. Dead
# entries removed 2026-07-08: readability, xmltodict, langcodes, language_data.
packages_to_collect = [
    "pyatv",
    "pychromecast",
    "async_upnp_client",
    "trafilatura",
    # Lemmy bodies use dynamically selected Markdown extensions (extra and
    # sane_lists), so static import analysis cannot see every required module.
    "markdown",
    "yt_dlp",
    "pytubefix",
    "aiohttp",
    "zeroconf",
    "pydantic",
    "lxml",
    "sgmllib",
    "six",
    "soupsieve",
    "defusedxml",
    "didl_lite",
    "ifaddr",
    "certifi",
    "curl_cffi",
    # Last-resort real-browser feed retrieval. Browser/driver binaries remain
    # runtime-managed in the writable per-user data directory.
    "seleniumbase",
    "selenium",
    "mycdp",
    # Tier-3 challenge escalation (driverless CDP Chromium + Turnstile
    # auto-click), imported lazily like the primary browser fallback.
    "pydoll",
    "websockets",
    "aiofiles",
    # extruct/mf2py: metadata enrichment. mf2py ships a 'backcompat-rules'
    # data directory it loads at import time; without collecting it, every
    # `import extruct` in the frozen app dies with FileNotFoundError.
    "extruct",
    "mf2py",
    # Rich full-text reader (opt-in); imported lazily so collect it explicitly.
    "wx_accessible_webview",
]


def _is_seleniumbase_runtime_artifact(item):
    """Keep downloaded browsers/drivers out of distributable builds."""
    source = str(item[0] if item else "").replace("\\", "/").lower()
    return "/seleniumbase/drivers/" in source and not source.endswith((".py", ".pyi"))


def _is_foreign_selenium_manager(item):
    """Keep only the Selenium Manager executable for the target platform."""
    source = str(item[0] if item else "").replace("\\", "/").lower()
    marker = "selenium/webdriver/common/"
    if marker not in source or "selenium-manager" not in source:
        return False
    if PLATFORM.startswith("win"):
        expected = "/windows/selenium-manager.exe"
    elif PLATFORM.startswith("darwin"):
        expected = "/macos/selenium-manager"
    else:
        expected = "/linux/selenium-manager"
    return not source.endswith(expected)

datas = []
binaries = []
# WebView2 loader for the rich full-text reader's wx.html2.WebView (Edge
# WebView2 backend). wxPython ships it inside its package; the reader falls
# back to plain text when the WebView2 runtime is missing.
try:
    import wx as _wx_for_webview2
    _webview2_dll = os.path.join(os.path.dirname(_wx_for_webview2.__file__), 'WebView2Loader.dll')
    if os.path.isfile(_webview2_dll):
        binaries.append((_webview2_dll, '.'))
except Exception:
    pass
hiddenimports = [
    "vlc",
    "trafilatura",
    # Rich full-text reader backend (WKWebView on macOS, WebKitGTK on Linux).
    # Imported lazily at runtime, so name it explicitly rather than relying on
    # bytecode scanning of lazy imports.
    "wx.html2",
    # Over-the-air translation updates, imported lazily inside functions.
    "core.po_compile",
    "core.translation_updates",
]


def add_binary(path, dest):
    src = Path(path)
    if src.is_file():
        binaries.append((str(src), dest))


def add_data(path, dest):
    src = Path(path)
    if src.exists():
        datas.append((str(src), dest))


def first_existing(paths):
    for path in paths:
        candidate = Path(path)
        if candidate.exists():
            return candidate
    return None


def add_unix_support_binaries():
    add_binary(BIN_DIR / "yt-dlp", "bin")
    add_binary(BIN_DIR / "deno", "bin")
    add_binary(BIN_DIR / "ffmpeg", "bin")


def add_macos_vlc_bundle():
    vlc_app = Path(os.environ.get("BLINDRSS_VLC_APP", "/Applications/VLC.app"))
    macos_dir = vlc_app / "Contents" / "MacOS"
    lib_dir = macos_dir / "lib"
    plugin_dir = first_existing([macos_dir / "plugins", macos_dir / "modules"])

    add_binary(lib_dir / "libvlc.dylib", "vlc/lib")
    add_binary(lib_dir / "libvlccore.dylib", "vlc/lib")
    if plugin_dir:
        add_data(plugin_dir, "vlc/plugins")


def add_linux_vlc_bundle():
    plugin_dir = first_existing(
        [
            os.environ.get("BLINDRSS_VLC_PLUGINS", ""),
            "/usr/lib/x86_64-linux-gnu/vlc/plugins",
            "/usr/lib/aarch64-linux-gnu/vlc/plugins",
            "/usr/lib/vlc/plugins",
        ]
    )
    lib_dir = first_existing(
        [
            os.environ.get("BLINDRSS_VLC_LIB_DIR", ""),
            "/usr/lib/x86_64-linux-gnu",
            "/usr/lib/aarch64-linux-gnu",
            "/usr/lib64",
            "/usr/lib",
        ]
    )
    if lib_dir:
        matches = sorted(glob.glob(str(Path(lib_dir) / "libvlc.so*")))
        if matches:
            add_binary(matches[0], "vlc/lib")
        matches = sorted(glob.glob(str(Path(lib_dir) / "libvlccore.so*")))
        if matches:
            add_binary(matches[0], "vlc/lib")
    if plugin_dir:
        add_data(plugin_dir, "vlc/plugins")


for pkg in packages_to_collect:
    try:
        spec = importlib.util.find_spec(pkg)
    except Exception:
        spec = None
    if spec is None:
        continue
    is_pkg = bool(spec.submodule_search_locations)
    if not is_pkg:
        hiddenimports.append(pkg)
        continue
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        hiddenimports.append(pkg)
        continue
    if pkg == "seleniumbase":
        # Runtime browsers and drivers live in BlindRSS's writable data
        # directory. Exclude any package-cache downloads present on the build
        # machine so they cannot accidentally inflate or stale the bundle.
        d = [item for item in d if not _is_seleniumbase_runtime_artifact(item)]
        b = [item for item in b if not _is_seleniumbase_runtime_artifact(item)]
        h = [
            module for module in h
            if not module.startswith("seleniumbase.behave")
            and module != "behave"
            and not module.startswith("behave.")
        ]
    elif pkg == "selenium":
        d = [item for item in d if not _is_foreign_selenium_manager(item)]
        b = [item for item in b if not _is_foreign_selenium_manager(item)]
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)

datas = [item for item in datas if not _is_foreign_selenium_manager(item)]
binaries = [item for item in binaries if not _is_foreign_selenium_manager(item)]

if importlib.util.find_spec("_webrtcvad") is not None:
    hiddenimports.append("_webrtcvad")

add_data(ROOT / "sounds", "sounds")
add_data(ROOT / "README.md", ".")
# MIT requires the notice to travel with every copy of the software (issue #92).
add_data(ROOT / "LICENSE", ".")

# UI translation catalogs (issue #44): locale/<lang>/LC_MESSAGES/blindrss.mo.
_locale_root = ROOT / "locale"
if _locale_root.is_dir():
    for _mo in _locale_root.glob("*/LC_MESSAGES/blindrss.mo"):
        add_data(_mo, str(Path("locale") / _mo.parent.parent.name / "LC_MESSAGES"))

# POSIX auto-update helper (macOS + Linux), placed next to the executable.
add_data(ROOT / "update_helper.sh", ".")

if PLATFORM.startswith("darwin"):
    add_unix_support_binaries()
    add_macos_vlc_bundle()
elif PLATFORM.startswith("linux"):
    add_unix_support_binaries()
    add_linux_vlc_bundle()

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[str(ROOT / "hooks")],
    hooksconfig={},
    runtime_hooks=[],
    # BlindRSS uses SeleniumBase only for its hidden browser fallback, never its
    # optional behave test runner. Keep that legacy package out of frozen builds.
    # Avoid bundling pytubefix's duplicate 100+ MB Node runtime; its signature
    # worker is routed through the Deno executable already shipped for yt-dlp.
    excludes=["behave", "seleniumbase.behave", "nodejs_wheel"],
    noarchive=False,
    optimize=0,
)
a.datas = [item for item in a.datas if not _is_foreign_selenium_manager(item)]
a.binaries = [item for item in a.binaries if not _is_foreign_selenium_manager(item)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BlindRSS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=_win_version_info,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BlindRSS",
)

if PLATFORM.startswith("darwin"):
    app = BUNDLE(
        coll,
        name="BlindRSS.app",
        icon=None,
        bundle_identifier="com.serrebi.BlindRSS",
        # VoiceOver/Finder read the version from the bundle. core/version.py is
        # the source of truth; BLINDRSS_APP_VERSION (exported by build.sh) is
        # only a fallback for builds run outside the repo.
        version=_app_version,
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "CFBundleName": "BlindRSS",
            "CFBundleDisplayName": "BlindRSS",
            "LSApplicationCategoryType": "public.app-category.news",
        },
    )
