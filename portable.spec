# -*- mode: python ; coding: utf-8 -*-

import glob
import importlib.util
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all


ROOT = Path(os.getcwd())
BIN_DIR = ROOT / "bin"
PLATFORM = sys.platform

packages_to_collect = [
    "pyatv",
    "pychromecast",
    "async_upnp_client",
    "trafilatura",
    "yt_dlp",
    "aiohttp",
    "zeroconf",
    "pydantic",
    "lxml",
    "readability",
    "sgmllib",
    "six",
    "soupsieve",
    "xmltodict",
    "defusedxml",
    "didl_lite",
    "ifaddr",
    "langcodes",
    "language_data",
    "certifi",
]

datas = []
binaries = []
hiddenimports = [
    "vlc",
    "trafilatura",
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
    datas.extend(d)
    binaries.extend(b)
    hiddenimports.extend(h)

try:
    import webrtcvad  # noqa: F401

    hiddenimports.append("webrtcvad")
except Exception:
    pass

add_data(ROOT / "sounds", "sounds")
add_data(ROOT / "README.md", ".")

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
        version=os.environ.get("BLINDRSS_APP_VERSION"),
        info_plist={
            "NSPrincipalClass": "NSApplication",
            "CFBundleName": "BlindRSS",
            "CFBundleDisplayName": "BlindRSS",
            "LSApplicationCategoryType": "public.app-category.news",
        },
    )
