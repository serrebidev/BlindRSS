"""Tests for cross-platform (Windows/macOS/Linux) auto-update logic."""

import os
import sys
import tarfile
import types
import zipfile

import core.update_config as update_config
import core.updater as updater


# --- update_config platform selection -----------------------------------------

def test_platform_manifest_and_extension(monkeypatch):
    monkeypatch.setattr(update_config.sys, "platform", "win32")
    assert update_config.current_platform() == "windows"
    assert update_config.platform_manifest_name() == "BlindRSS-update.json"
    assert update_config.platform_asset_extension() == ".zip"

    monkeypatch.setattr(update_config.sys, "platform", "darwin")
    assert update_config.current_platform() == "macos"
    assert update_config.platform_manifest_name() == "BlindRSS-update-macos.json"
    assert update_config.platform_asset_extension() == ".zip"

    monkeypatch.setattr(update_config.sys, "platform", "linux")
    assert update_config.current_platform() == "linux"
    assert update_config.platform_manifest_name() == "BlindRSS-update-linux.json"
    assert update_config.platform_asset_extension() == ".tar.gz"


# --- archive extraction + staging resolution ----------------------------------

def test_extract_archive_zip(tmp_path):
    z = tmp_path / "a.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("BlindRSS.app/Contents/MacOS/BlindRSS", "bin")
    dest = tmp_path / "z"
    dest.mkdir()
    updater._extract_archive(str(z), str(dest))
    assert updater._find_macos_app_staging(str(dest)).endswith("BlindRSS.app")


def test_extract_archive_targz_and_linux_staging(tmp_path):
    src = tmp_path / "BlindRSS"
    src.mkdir()
    (src / "BlindRSS").write_text("bin")
    t = tmp_path / "a.tar.gz"
    with tarfile.open(t, "w:gz") as tf:
        tf.add(str(src), arcname="BlindRSS")
    dest = tmp_path / "t"
    dest.mkdir()
    updater._extract_archive(str(t), str(dest))
    staging = updater._find_linux_staging(str(dest))
    assert staging and staging.endswith("BlindRSS")
    assert os.path.isfile(os.path.join(staging, "BlindRSS"))


def test_extract_archive_rejects_unknown(tmp_path):
    bad = tmp_path / "a.7z"
    bad.write_text("x")
    try:
        updater._extract_archive(str(bad), str(tmp_path))
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- macOS bundle root resolution ---------------------------------------------

def test_macos_app_bundle_root(monkeypatch, tmp_path):
    macos = tmp_path / "BlindRSS.app" / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    exe = macos / "BlindRSS"
    exe.write_text("x")
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    root = updater._macos_app_bundle_root()
    assert root and root.endswith("BlindRSS.app")


def test_macos_app_bundle_root_none_when_not_bundle(monkeypatch, tmp_path):
    exe = tmp_path / "BlindRSS"
    exe.write_text("x")
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater._macos_app_bundle_root() is None


# --- is_update_supported per platform -----------------------------------------

def test_is_update_supported_requires_helper_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "current_platform", lambda: "linux")
    monkeypatch.setattr(updater, "APP_DIR", str(tmp_path))
    assert updater.is_update_supported() is False
    (tmp_path / "update_helper.sh").write_text("#!/bin/sh\n")
    assert updater.is_update_supported() is True


def test_is_update_supported_macos_needs_bundle(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "current_platform", lambda: "macos")
    monkeypatch.setattr(updater, "APP_DIR", str(tmp_path))
    (tmp_path / "update_helper.sh").write_text("#!/bin/sh\n")
    monkeypatch.setattr(updater, "_macos_app_bundle_root", lambda: None)
    assert updater.is_update_supported() is False
    monkeypatch.setattr(updater, "_macos_app_bundle_root", lambda: "/x/BlindRSS.app")
    assert updater.is_update_supported() is True


def test_is_update_supported_false_when_not_frozen(monkeypatch):
    monkeypatch.setattr(updater.sys, "frozen", False, raising=False)
    assert updater.is_update_supported() is False


# --- check_for_updates platform manifest selection ----------------------------

def _release(tag):
    return {
        "tag_name": tag,
        "published_at": "2026-01-01T00:00:00Z",
        "assets": [
            {"name": "BlindRSS-update-linux.json", "browser_download_url": "http://x/m"},
            {"name": f"BlindRSS-linux-{tag}.tar.gz", "browser_download_url": "http://x/a"},
        ],
    }


def test_check_for_updates_selects_linux_manifest(monkeypatch):
    monkeypatch.setattr(updater, "current_platform", lambda: "linux")
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: (_release("v999.0.0"), None))
    manifest = {
        "version": "v999.0.0",
        "asset": "BlindRSS-linux-v999.0.0.tar.gz",
        "download_url": "http://x/a",
        "sha256": "a" * 64,
    }
    monkeypatch.setattr(updater, "_download_json", lambda url, timeout=20: (manifest, None))
    res = updater.check_for_updates()
    assert res.status == "update_available"
    assert res.info is not None
    assert res.info.asset_name == "BlindRSS-linux-v999.0.0.tar.gz"


def test_check_for_updates_rejects_wrong_extension(monkeypatch):
    monkeypatch.setattr(updater, "current_platform", lambda: "linux")
    monkeypatch.setattr(updater, "_fetch_latest_release", lambda: (_release("v999.0.0"), None))
    manifest = {
        "version": "v999.0.0",
        "asset": "BlindRSS-linux-v999.0.0.zip",  # wrong extension for linux
        "download_url": "http://x/a",
        "sha256": "a" * 64,
    }
    monkeypatch.setattr(updater, "_download_json", lambda url, timeout=20: (manifest, None))
    res = updater.check_for_updates()
    assert res.status == "error"
    assert ".tar.gz" in res.message


# --- helper launch + per-platform apply ---------------------------------------

def test_launch_posix_helper_builds_command(monkeypatch, tmp_path):
    captured = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return types.SimpleNamespace(pid=123)

    monkeypatch.setattr(updater.subprocess, "Popen", fake_popen)
    helper = tmp_path / "update_helper.sh"
    helper.write_text("#!/bin/sh\n")
    temp_root = tmp_path / "BlindRSS_update_x"
    temp_root.mkdir()

    ok, _msg = updater._launch_posix_helper(
        str(helper),
        "linux",
        install_target="/opt/app",
        staging_root="/tmp/stage",
        relaunch_path="/opt/app/BlindRSS",
        temp_root=str(temp_root),
    )
    assert ok
    cmd = captured["cmd"]
    assert cmd[0] == "/bin/sh"
    assert cmd[2] == str(os.getpid())
    assert cmd[3:7] == ["linux", "/opt/app", "/tmp/stage", "/opt/app/BlindRSS"]
    assert cmd[7] == str(temp_root)
    # Helper is copied into temp_root so the swap can't delete it mid-run.
    assert os.path.isfile(os.path.join(str(temp_root), "update_helper.sh"))


def test_apply_linux_invokes_helper(monkeypatch, tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "update_helper.sh").write_text("#!/bin/sh\n")
    extract = tmp_path / "extract"
    extract.mkdir()
    stage = extract / "BlindRSS"
    stage.mkdir()
    (stage / "BlindRSS").write_text("bin")

    calls = {}

    def fake_launch(helper, platform, *, install_target, staging_root, relaunch_path, temp_root):
        calls.update(
            platform=platform,
            install_target=install_target,
            staging_root=staging_root,
            relaunch_path=relaunch_path,
        )
        return True, "ok"

    monkeypatch.setattr(updater, "_launch_posix_helper", fake_launch)
    ok, _msg = updater._apply_linux(str(install), str(tmp_path / "tmp"), str(extract), lambda *a: True)
    assert ok
    assert calls["platform"] == "linux"
    assert calls["install_target"] == str(install)
    assert calls["staging_root"] == str(stage)
    assert calls["relaunch_path"] == os.path.join(str(install), "BlindRSS")


def test_apply_macos_invokes_helper(monkeypatch, tmp_path):
    install = tmp_path / "MacOS"
    install.mkdir()
    (install / "update_helper.sh").write_text("#!/bin/sh\n")
    extract = tmp_path / "extract"
    extract.mkdir()
    app = extract / "BlindRSS.app" / "Contents" / "MacOS"
    app.mkdir(parents=True)
    (app / "BlindRSS").write_text("bin")

    monkeypatch.setattr(updater, "_macos_app_bundle_root", lambda: "/Applications/BlindRSS.app")
    monkeypatch.setattr(updater, "_verify_macos_codesign", lambda p: (True, ""))

    calls = {}

    def fake_launch(helper, platform, *, install_target, staging_root, relaunch_path, temp_root):
        calls.update(
            platform=platform,
            install_target=install_target,
            staging_root=staging_root,
            relaunch_path=relaunch_path,
        )
        return True, "ok"

    monkeypatch.setattr(updater, "_launch_posix_helper", fake_launch)
    ok, _msg = updater._apply_macos(str(install), str(tmp_path / "tmp"), str(extract), lambda *a: True)
    assert ok
    assert calls["platform"] == "macos"
    assert calls["install_target"] == "/Applications/BlindRSS.app"
    assert calls["staging_root"].endswith("BlindRSS.app")
    assert calls["relaunch_path"] == "/Applications/BlindRSS.app"


def test_apply_windows_installer_verifies_and_launches_helper(monkeypatch, tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    (install / "update_helper.bat").write_text("@echo off\n")
    installer = tmp_path / "BlindRSS-Setup-v2.0.0.exe"
    installer.write_bytes(b"setup")
    info = updater.UpdateInfo(
        version=updater.Version("2.0.0"),
        tag="v2.0.0",
        published_at="",
        notes_summary="",
        asset_name=installer.name,
        download_url="https://example.test/setup.exe",
        sha256="a" * 64,
        signing_thumbprints=("AABBCC",),
        asset_kind="installer",
    )

    monkeypatch.setattr(
        updater,
        "_verify_authenticode_signature",
        lambda path, thumbs: (path == str(installer) and thumbs == ("AABBCC",), ""),
    )
    captured = {}

    def fake_launch(helper, parent_pid, install_dir, staging_root, **kwargs):
        captured.update(
            helper=helper,
            install_dir=install_dir,
            staging_root=staging_root,
            kwargs=kwargs,
        )
        return True, ""

    monkeypatch.setattr(updater, "_launch_update_helper", fake_launch)
    ok, message = updater._apply_windows_installer(
        info,
        str(install),
        str(tmp_path),
        str(installer),
        False,
        lambda *_args: True,
    )

    assert ok, message
    assert captured["install_dir"] == str(install)
    assert captured["staging_root"] == ""
    assert captured["kwargs"]["installer_path"] == str(installer)
