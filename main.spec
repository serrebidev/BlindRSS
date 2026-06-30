# -*- mode: python ; coding: utf-8 -*-

import os
import re
import sys
import importlib.util
from PyInstaller.utils.hooks import collect_all
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
                StringStruct('LegalCopyright', ''),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [0x0409, 0x04B0])]),
    ],
)

# VLC path - adjust this if VLC is installed elsewhere
vlc_path = r'C:\Program Files\VideoLAN\VLC'
bin_path = os.path.join(os.getcwd(), 'bin')

# Exhaustive collection of dependencies as mentioned in agents.md
packages_to_collect = [
    'pyatv', 'pychromecast', 'async_upnp_client', 'trafilatura', 
    'yt_dlp', 'aiohttp', 'zeroconf', 'pydantic', 'lxml', 
    'readability', 'sgmllib', 'six', 'soupsieve', 'xmltodict', 
    'defusedxml', 'didl_lite', 'ifaddr', 'langcodes', 'language_data',
    'certifi', 'curl_cffi'
]

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
]

try:
    import webrtcvad  # noqa: F401
    hiddenimports.append('webrtcvad')
except Exception:
    pass

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
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)

# Include update helper script in the app directory.
helper_path = os.path.join(os.getcwd(), 'update_helper.bat')
if os.path.isfile(helper_path):
    datas.append((helper_path, '.'))

# Add VLC plugins
datas.append((os.path.join(vlc_path, 'plugins'), 'plugins'))

# Add sounds
datas.append(('sounds', 'sounds'))

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
    excludes=[],
    noarchive=False,
    optimize=0,
)
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
