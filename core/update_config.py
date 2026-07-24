# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import sys

APP_NAME = "BlindRSS"
EXE_NAME = "BlindRSS.exe"

GITHUB_OWNER = "serrebidev"
GITHUB_REPO = "BlindRSS"

# Windows names, kept as the canonical/back-compatible values so existing Windows
# clients (which look for exactly these) keep updating.
UPDATE_MANIFEST_NAME = "BlindRSS-update.json"
UPDATE_ASSET_PREFIX = "BlindRSS"
UPDATE_ASSET_EXTENSION = ".zip"

# Per-platform update manifests. Each one is uploaded by the build flow that
# produces that platform's asset, so the manifest's sha256 always matches the
# asset attached to the same GitHub release.
UPDATE_MANIFEST_NAMES = {
    "windows": "BlindRSS-update.json",
    "macos": "BlindRSS-update-macos.json",
    "linux": "BlindRSS-update-linux.json",
}

# Expected asset extension per platform (used to sanity-check the manifest).
UPDATE_ASSET_EXTENSIONS = {
    "windows": ".zip",
    "macos": ".zip",
    "linux": ".tar.gz",
}

# Update helper scripts bundled next to the executable.
WINDOWS_UPDATE_HELPER_NAME = "update_helper.bat"
POSIX_UPDATE_HELPER_NAME = "update_helper.sh"


def current_platform():
    """Return 'windows', 'macos', 'linux', or None for the running platform."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return None


def platform_manifest_name(platform=None):
    platform = platform or current_platform()
    return UPDATE_MANIFEST_NAMES.get(platform or "", UPDATE_MANIFEST_NAME)


def platform_asset_extension(platform=None):
    platform = platform or current_platform()
    return UPDATE_ASSET_EXTENSIONS.get(platform or "", UPDATE_ASSET_EXTENSION)
