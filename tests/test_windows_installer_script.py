from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "installer" / "BlindRSS.iss"
BUILD = ROOT / "build.bat"


def test_installer_is_per_user_and_marks_installed_copy():
    text = ISS.read_text(encoding="utf-8")

    assert "DefaultDirName={localappdata}\\Programs\\{#MyAppName}" in text
    assert "PrivilegesRequired=lowest" in text
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


def test_build_detects_per_user_and_standard_inno_setup_paths():
    text = BUILD.read_text(encoding="utf-8")

    assert "%LOCALAPPDATA%\\Programs\\Inno Setup 6\\ISCC.exe" in text
    assert "%ProgramFiles%\\Inno Setup 6\\ISCC.exe" in text
    assert "%ProgramFiles(x86)%\\Inno Setup 6\\ISCC.exe" in text
    assert "INNO_SETUP_COMPILER" in text
    assert 'where ISCC.exe' in text


def test_release_uploads_installer_and_manifest_contains_installer_hash():
    text = BUILD.read_text(encoding="utf-8")

    assert "--installer-asset-name" in text
    assert "--installer-sha256" in text
    assert '"%INSTALLER_PATH%" "%MANIFEST_PATH%"' in text
