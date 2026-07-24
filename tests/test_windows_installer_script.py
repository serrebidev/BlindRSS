# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "BlindRSS.iss"
BUILD = ROOT / "build.bat"
WORKFLOW = ROOT / ".github" / "workflows" / "cross-platform-release.yml"


def test_installer_targets_program_files_and_marks_installed_copy():
    text = ISS.read_text(encoding="utf-8")

    # Per-machine install into Program Files (x64 -> "Program Files",
    # x86 -> "Program Files (x86)" via {autopf} + 64-bit install mode).
    assert "DefaultDirName={autopf}\\{#MyAppName}" in text
    assert "PrivilegesRequired=admin" in text
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in text

    # The old per-user model must be gone so we never regress to LocalAppData.
    assert "{localappdata}\\Programs" not in text
    assert "PrivilegesRequired=lowest" not in text

    # The installed-build marker still drives roaming-data mode at runtime.
    assert 'DestName: ".windows-installed"' in text
    assert "UninstallDisplayIcon={app}\\{#MyAppExeName}" in text

    files_line = next(line for line in text.splitlines() if 'Source: "..\\dist\\BlindRSS\\*"' in line)
    for user_data in (
        "config.json",
        "rss.db",
        "rss.db-wal",
        "rss.db-shm",
        "rss.db-journal",
        "podcasts\\*",
        "ytplay_cache\\*",
        "youtube_cookies.txt",
    ):
        assert user_data in files_line


def test_build_detects_inno_setup_compiler_paths():
    text = BUILD.read_text(encoding="utf-8")

    # Locating the Inno Setup *compiler* still probes the per-user and standard
    # install locations (this is about ISCC.exe, not BlindRSS's install target).
    assert "%LOCALAPPDATA%\\Programs\\Inno Setup 6\\ISCC.exe" in text
    assert "%ProgramFiles%\\Inno Setup 6\\ISCC.exe" in text
    assert "%ProgramFiles(x86)%\\Inno Setup 6\\ISCC.exe" in text
    assert "INNO_SETUP_COMPILER" in text
    assert 'where ISCC.exe' in text


def test_build_python_missing_message_is_safe_inside_cmd_block():
    text = BUILD.read_text(encoding="utf-8")

    # Parentheses are control syntax even in an echo inside a parenthesized
    # cmd.exe block.  Keep them escaped so dry-run/release can be parsed.
    assert "available ^(python/py^)." in text
    assert "available (python/py)." not in text


def test_release_uploads_installer_and_manifest_contains_installer_hash():
    text = BUILD.read_text(encoding="utf-8")

    assert "--installer-asset-name" in text
    assert "--installer-sha256" in text
    assert '"%INSTALLER_PATH%" "%MANIFEST_PATH%"' in text


def test_windows_release_skips_redundant_windows_ci_build():
    build_text = BUILD.read_text(encoding="utf-8")
    workflow_text = WORKFLOW.read_text(encoding="utf-8")

    assert '-f build_windows=false' in build_text
    assert "build_windows:" in workflow_text
    assert "inputs.build_windows" in workflow_text
