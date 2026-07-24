# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shadow of yt-dlp's bundled PyInstaller hook (yt_dlp/__pyinstaller/hook-yt_dlp.py).

The upstream hook calls ``collect_submodules('urllib3')``, which tries to
import every urllib3 subpackage in an isolated process. ``urllib3.contrib.
emscripten`` only imports under Pyodide (it needs the ``js`` module), so every
build logs:

    WARNING: Failed to collect submodules for 'urllib3.contrib.emscripten'
    because importing 'urllib3.contrib.emscripten' raised: ModuleNotFoundError:
    No module named 'js'

This user hook (hookspath has priority over the entry-point hook) executes the
upstream hook file unchanged, except that ``collect_submodules`` is wrapped to
skip the emscripten subpackage during the urllib3 scan. The resulting bundle is
identical: that subpackage was never collected anyway (its import always
failed); only the warning goes away. Upstream hook updates are picked up
automatically because the real hook source is executed, not copied.
"""

from __future__ import annotations

import importlib.util
import os

import PyInstaller.utils.hooks as _hookutils

_spec = importlib.util.find_spec("yt_dlp")
if _spec is None or not _spec.origin:
    raise RuntimeError("hook-yt_dlp shadow: cannot locate the yt_dlp package")

_upstream_hook = os.path.join(
    os.path.dirname(_spec.origin), "__pyinstaller", "hook-yt_dlp.py"
)
if not os.path.isfile(_upstream_hook):
    raise RuntimeError(
        "hook-yt_dlp shadow: upstream hook not found at %r; yt-dlp changed its "
        "packaging -- update or delete hooks/hook-yt_dlp.py" % _upstream_hook
    )


def _is_not_emscripten(name):
    return name != "urllib3.contrib.emscripten" and not name.startswith(
        "urllib3.contrib.emscripten."
    )


_orig_collect_submodules = _hookutils.collect_submodules


def _filtered_collect_submodules(package, *args, **kwargs):
    if package == "urllib3" and "filter" not in kwargs and not args:
        kwargs["filter"] = _is_not_emscripten
    return _orig_collect_submodules(package, *args, **kwargs)


_namespace = {"__file__": _upstream_hook, "__name__": "hook_yt_dlp_upstream"}
_hookutils.collect_submodules = _filtered_collect_submodules
try:
    with open(_upstream_hook, "r", encoding="utf-8") as _f:
        exec(compile(_f.read(), _upstream_hook, "exec"), _namespace)
finally:
    _hookutils.collect_submodules = _orig_collect_submodules

hiddenimports = _namespace.get("hiddenimports", [])
excludedimports = _namespace.get("excludedimports", [])
datas = _namespace.get("datas", [])
binaries = _namespace.get("binaries", [])
