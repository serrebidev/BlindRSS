# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from __future__ import annotations

from PyInstaller.compat import importlib_metadata
from PyInstaller.utils.hooks import copy_metadata

hiddenimports = ["webrtcvad"]

datas = []

# The project uses `webrtcvad-wheels` which provides the `webrtcvad` module but
# stores distribution metadata under the `webrtcvad-wheels` name.
#
# The default hook in pyinstaller-hooks-contrib tries to `copy_metadata("webrtcvad")`,
# which fails with PackageNotFoundError when only `webrtcvad-wheels` is installed.
for dist_name in ("webrtcvad", "webrtcvad-wheels", "webrtcvad_wheels"):
    try:
        datas += copy_metadata(dist_name)
        break
    except importlib_metadata.PackageNotFoundError:
        pass
