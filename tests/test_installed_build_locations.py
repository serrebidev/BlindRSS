# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Program Files install model: program in Program Files, mutable data elsewhere.

These lock in that an installed (Program Files) build never writes to its own
read-only install directory at runtime:
  * the runtime-managed yt-dlp.exe lives under per-user LocalAppData, and
  * episode downloads default to the user's Downloads folder.
Portable / source runs keep using a writable folder beside the app.
"""

import os

import core.config as config_mod
import core.dependency_check as dep_mod


# ---------------------------------------------------------------------------
# Runtime yt-dlp bin directory (core/dependency_check.py)
# ---------------------------------------------------------------------------


def test_installed_build_keeps_ytdlp_under_localappdata(monkeypatch):
    monkeypatch.setattr(dep_mod, "is_windows_installed_build", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\alice\AppData\Local")

    assert dep_mod._ytdlp_runtime_bin_dir() == os.path.join(
        r"C:\Users\alice\AppData\Local", "BlindRSS", "bin"
    )


def test_portable_frozen_build_keeps_ytdlp_beside_executable(tmp_path, monkeypatch):
    monkeypatch.setattr(dep_mod, "is_windows_installed_build", lambda: False)
    monkeypatch.setattr(dep_mod.sys, "frozen", True, raising=False)
    exe = tmp_path / "BlindRSS" / "BlindRSS.exe"
    monkeypatch.setattr(dep_mod.sys, "executable", str(exe))

    assert dep_mod._ytdlp_runtime_bin_dir() == os.path.join(str(tmp_path / "BlindRSS"), "bin")


def test_source_run_keeps_ytdlp_in_repo_bin(monkeypatch):
    monkeypatch.setattr(dep_mod, "is_windows_installed_build", lambda: False)
    monkeypatch.setattr(dep_mod.sys, "frozen", False, raising=False)

    repo_root = os.path.abspath(os.path.join(os.path.dirname(dep_mod.__file__), ".."))
    assert dep_mod._ytdlp_runtime_bin_dir() == os.path.join(repo_root, "bin")


# ---------------------------------------------------------------------------
# Default download directory (core/config.py)
# ---------------------------------------------------------------------------


def test_installed_build_downloads_default_to_downloads_folder(monkeypatch):
    monkeypatch.setattr(config_mod, "is_windows_installed_build", lambda: True)
    monkeypatch.setattr(config_mod, "_windows_downloads_dir", lambda: r"C:\Users\alice\Downloads")

    assert config_mod._default_download_dir() == os.path.join(
        r"C:\Users\alice\Downloads", "BlindRSS"
    )


def test_portable_build_downloads_default_to_app_podcasts(monkeypatch):
    monkeypatch.setattr(config_mod, "is_windows_installed_build", lambda: False)
    monkeypatch.setattr(config_mod, "APP_DIR", r"C:\PortableApps\BlindRSS")

    assert config_mod._default_download_dir() == os.path.join(
        r"C:\PortableApps\BlindRSS", "podcasts"
    )
