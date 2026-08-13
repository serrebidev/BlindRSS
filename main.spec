# -*- mode: python ; coding: utf-8 -*-
# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import os
import re
import sys
import warnings
import importlib.util
from PyInstaller.utils.hooks import collect_all

# Build-time warning hygiene (keep in sync with portable.spec). These
# UserWarnings fire while PyInstaller imports third-party packages to scan
# them; the remaining warning is not fixable in this repo and does not affect
# the app at runtime:
# - pydantic (transitive dep of the pyatv casting stack) warns that its
#   bundled V1 compat shim is unsupported on Python >= 3.14. pyatv still uses
#   the V1 API, so pydantic.v1 must stay in the bundle.
_BUILD_WARNING_IGNORES = (
    "Core Pydantic V1 functionality",
)
for _msg in _BUILD_WARNING_IGNORES:
    # Filter this (spec/Analysis) process; `message` is a regex matched at the
    # start of the warning text -- these literals contain no regex chars.
    warnings.filterwarnings("ignore", message=_msg, category=UserWarning)
# PyInstaller also imports packages in isolated subprocesses (hook scans),
# which only see env-level filters. PYTHONWARNINGS message fields are literal
# prefix matches. Build-time env only; nothing leaks into the frozen app.
_pythonwarnings = [f"ignore:{_msg}:UserWarning" for _msg in _BUILD_WARNING_IGNORES]
if os.environ.get("PYTHONWARNINGS"):
    _pythonwarnings.insert(0, os.environ["PYTHONWARNINGS"])
os.environ["PYTHONWARNINGS"] = ",".join(_pythonwarnings)
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo,
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
)


def _read_app_version():
    """Read APP_VERSION from core/version.py without importing the app package."""
    version_file = os.path.join(os.getcwd(), 'core', 'version.py')
    try:
        with open(version_file, 'r', encoding='utf-8') as f:
            m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', f.read())
            if m:
                return m.group(1)
    except Exception:
        pass
    return os.environ.get('BLINDRSS_APP_VERSION', '0.0.0')


def _version_tuple(v):
    nums = [int(x) for x in re.findall(r'\d+', v)[:4]]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums[:4])


_app_version = _read_app_version()
_vt = _version_tuple(_app_version)

# Embed a Windows VERSIONINFO resource so screen readers (NVDA "Say Product Name
# and Version", JAWS) and Windows itself can report the app name and version.
# Without this, NVDA reports "Application unknown, version not detected".
version_info = VSVersionInfo(
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

# VLC path - adjust this if VLC is installed elsewhere
vlc_path = r'C:\Program Files\VideoLAN\VLC'
bin_path = os.path.join(os.getcwd(), 'bin')

# Packages whose data files / dynamic imports PyInstaller's analysis can miss.
# Audited 2026-07-08: every entry is either imported directly by the app
# (casting: pyatv/pychromecast/async_upnp_client; extraction: trafilatura,
# yt_dlp/pytubefix; transport: curl_cffi) or an installed transitive dependency of one
# (aiohttp/zeroconf/pydantic <- casting stack; lxml/soupsieve <- parsers;
# sgmllib <- feedparser; six <- html5lib; defusedxml/didl_lite/ifaddr <-
# async_upnp_client/zeroconf; certifi <- TLS in frozen builds). Dropped dead
# entries that were never installed and never imported: readability,
# xmltodict, langcodes, language_data.
packages_to_collect = [
    'pyatv', 'pychromecast', 'async_upnp_client', 'trafilatura', 'markdown',
    'yt_dlp', 'pytubefix', 'aiohttp', 'zeroconf', 'pydantic', 'lxml',
    'sgmllib', 'six', 'soupsieve',
    'defusedxml', 'didl_lite', 'ifaddr',
    'certifi', 'curl_cffi',
    # Chromium v20 cookie decryption (core/chromium_cookies.py) uses
    # AES-256-GCM/ChaCha20-Poly1305 from cryptography, imported lazily inside
    # the helpers, so PyInstaller's startup-graph analysis misses it. Its hook
    # also bundles the C extension backends the AEAD classes need.
    'cryptography',
    # Last-resort real-browser feed retrieval. Imported lazily after every
    # ordinary HTTP attempt fails, so PyInstaller cannot discover it from the
    # normal startup graph. Browser/driver binaries are downloaded per-user.
    'seleniumbase', 'selenium', 'mycdp',
    # Tier-3 challenge escalation (driverless CDP Chromium + Turnstile
    # auto-click), likewise imported lazily and only after the UC session
    # settles on a challenge it cannot clear.
    'pydoll', 'websockets', 'aiofiles',
    # extruct/mf2py: metadata enrichment. mf2py ships a 'backcompat-rules'
    # data directory it loads at import time; without collecting it, every
    # `import extruct` in the frozen app dies with FileNotFoundError.
    'extruct', 'mf2py',
    # Rich full-text reader (opt-in). Pure-python but imported lazily, so
    # PyInstaller's analysis misses it unless collected explicitly.
    'wx_accessible_webview',
    # Screen-reader speech + Braille announcements (issue #67). Ships per-output
    # backends plus bundled DLLs/sound data it loads at runtime, and is imported
    # lazily, so collect the whole package (with its deps) or the frozen build
    # falls back to the direct NVDA/JAWS speech path only.
    'accessible_output2', 'platform_utils', 'libloader',
]


def _is_seleniumbase_runtime_artifact(item):
    """Keep downloaded browsers/drivers out of distributable builds."""
    source = str(item[0] if item else "").replace('\\', '/').lower()
    return '/seleniumbase/drivers/' in source and not source.endswith(('.py', '.pyi'))


def _is_foreign_selenium_manager(item):
    """Drop Linux/macOS Selenium Manager binaries from the Windows build."""
    source = str(item[0] if item else "").replace('\\', '/').lower()
    marker = 'selenium/webdriver/common/'
    if marker not in source or 'selenium-manager' not in source:
        return False
    return not source.endswith('/windows/selenium-manager.exe')

datas = []
binaries = [
    (os.path.join(vlc_path, 'libvlc.dll'), '.'),
    (os.path.join(vlc_path, 'libvlccore.dll'), '.'),
    (os.path.join(bin_path, 'yt-dlp.exe'), 'bin'),
    (os.path.join(bin_path, 'deno.exe'), 'bin'),
]
hiddenimports = [
    'vlc',
    'trafilatura',
    # Over-the-air translation updates. Imported lazily inside functions (so a
    # missing module would degrade to "no updates" in silence), so name them
    # explicitly rather than relying on bytecode scanning of lazy imports.
    'core.po_compile',
    'core.translation_updates',
]

if importlib.util.find_spec('_webrtcvad') is not None:
    hiddenimports.append('_webrtcvad')

if importlib.util.find_spec('win32com') is not None:
    hiddenimports.extend(['pythoncom', 'pywintypes', 'win32com', 'win32com.client'])

# WebView2 loader for the rich full-text reader's wx.html2.WebView (Edge
# WebView2 backend). wxPython ships WebView2Loader.dll inside its package;
# include it so the frozen build can create the control. The Edge WebView2
# *runtime* is a system component (present on Windows 11 and updated Windows
# 10); the reader falls back to plain text when it is missing.
try:
    import wx as _wx_for_webview2
    _webview2_dll = os.path.join(os.path.dirname(_wx_for_webview2.__file__), 'WebView2Loader.dll')
    if os.path.isfile(_webview2_dll):
        binaries.append((_webview2_dll, '.'))
except Exception:
    pass

nvda_controller_path = os.path.join(bin_path, 'nvdaControllerClient.dll')
if os.path.isfile(nvda_controller_path):
    binaries.append((nvda_controller_path, 'bin'))
for nvda_doc in ('nvdaControllerClient-license.txt', 'nvdaControllerClient-readme.md'):
    nvda_doc_path = os.path.join(bin_path, nvda_doc)
    if os.path.isfile(nvda_doc_path):
        datas.append((nvda_doc_path, 'bin'))

for pkg in packages_to_collect:
    try:
        spec = importlib.util.find_spec(pkg)
    except Exception:
        spec = None
    if spec is None:
        # Module not installed in this environment; skip it.
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
    if pkg == 'seleniumbase':
        # A developer may already have let SeleniumBase populate its package
        # driver cache. BlindRSS deliberately downloads those artifacts into
        # its writable per-user data directory instead of shipping stale,
        # unsigned-at-build-time browser binaries in the application bundle.
        d = [item for item in d if not _is_seleniumbase_runtime_artifact(item)]
        b = [item for item in b if not _is_seleniumbase_runtime_artifact(item)]
        # collect_all reports the optional Behave integration as hidden imports.
        # Analysis excludes that test-runner path below, but feeding the names to
        # Analysis anyway produces misleading "Hidden import ... not found"
        # ERROR lines. Remove them before they reach the hidden-import queue.
        h = [
            module for module in h
            if not module.startswith('seleniumbase.behave')
            and module != 'behave'
            and not module.startswith('behave.')
        ]
    elif pkg == 'selenium':
        # The wheel contains manager executables for all three desktop
        # platforms. They are mutually unusable, and SeleniumBase manages the
        # actual browser/driver runtime in BlindRSS's per-user data directory.
        d = [item for item in d if not _is_foreign_selenium_manager(item)]
        b = [item for item in b if not _is_foreign_selenium_manager(item)]
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)

# collect_all(seleniumbase) can pull Selenium's package data transitively
# before the explicit selenium pass above gets a chance to filter it.
datas = [item for item in datas if not _is_foreign_selenium_manager(item)]
binaries = [item for item in binaries if not _is_foreign_selenium_manager(item)]

# Include update helper script in the app directory.
helper_path = os.path.join(os.getcwd(), 'update_helper.bat')
if os.path.isfile(helper_path):
    datas.append((helper_path, '.'))

# Add VLC plugins
datas.append((os.path.join(vlc_path, 'plugins'), 'plugins'))

# Add sounds
datas.append(('sounds', 'sounds'))

# Ship the license text with the build; MIT requires the notice to travel with
# every copy of the software (issue #92).
if os.path.isfile('LICENSE'):
    datas.append(('LICENSE', '.'))

# Add UI translation catalogs (issue #44): locale/<lang>/LC_MESSAGES/blindrss.mo.
# Coexists with VLC's locale tree below (different .mo domain names).
if os.path.isdir('locale'):
    for lang_dir in os.listdir('locale'):
        mo_path = os.path.join('locale', lang_dir, 'LC_MESSAGES', 'blindrss.mo')
        if os.path.isfile(mo_path):
            datas.append((mo_path, os.path.join('locale', lang_dir, 'LC_MESSAGES')))

# Add VLC assets (locales, Lua scripts, HRTF data)
for asset_dir in ('lua', 'locale', 'hrtfs'):
    asset_path = os.path.join(vlc_path, asset_dir)
    if os.path.isdir(asset_path):
        datas.append((asset_path, asset_dir))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[os.path.join(os.getcwd(), 'hooks')],
    hooksconfig={},
    runtime_hooks=[],
    # SeleniumBase optionally integrates with behave, but BlindRSS never uses
    # that test-runner path. Excluding it avoids importing behave 1.2.6's
    # Python-3.14-invalid legacy regex strings during frozen-app analysis.
    # pytubefix normally pulls a complete Node distribution solely for its
    # signature worker. core.youtube_pytubefix injects the tiny import surface
    # it needs and runs that worker through BlindRSS's existing bundled Deno.
    excludes=['behave', 'seleniumbase.behave', 'nodejs_wheel'],
    noarchive=False,
    optimize=0,
)
# Hooks can add package data and ctypes aliases after our input lists have been
# normalized. Apply the platform trim once more to Analysis's final TOCs.
a.datas = [item for item in a.datas if not _is_foreign_selenium_manager(item)]
a.binaries = [
    item for item in a.binaries
    if not _is_foreign_selenium_manager(item)
    and str(item[0]).replace('\\', '/').lower()
    not in {'libvlc.dylib', 'libvlccore.dylib'}
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BlindRSS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Use debug mode to show a console when needed
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BlindRSS',
)
