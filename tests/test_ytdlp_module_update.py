# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Tests for the runtime self-update of the embedded yt_dlp module."""

import io
import os
import sys
import zipfile

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import dependency_check as dc


def _make_wheel(top_package, version=None, extra=None):
    """Build an in-memory wheel zip containing one top-level package."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(f"{top_package}/__init__.py", "# pkg\n")
        if version is not None:
            zf.writestr(
                f"{top_package}/version.py", f"__version__ = '{version}'\n"
            )
        # Metadata and junk outside the package must be skipped.
        zf.writestr(f"{top_package}-0.dist-info/METADATA", "Name: x\n")
        zf.writestr("README.md", "not package data\n")
        for name, body in (extra or {}).items():
            zf.writestr(name, body)
    return buf.getvalue()


class TestNightlyChannel:
    def test_nightly_pypi_and_binary_spellings_compare_equal(self):
        assert dc._ytdlp_version_key("2026.10.10.233141.dev0") == dc._ytdlp_version_key(
            "2026.10.10.233141"
        )
        assert dc._ytdlp_version_key("2026.10.10.233141") > dc._ytdlp_version_key("2026.08.19")

    def test_pre_release_wheel_beats_stale_stable(self, monkeypatch):
        def wheel(name):
            return [{"packagetype": "bdist_wheel", "filename": name, "url": "https://x/" + name,
                     "digests": {"sha256": "abc"}}]

        payload = {
            "info": {"version": "2026.8.19"},
            "urls": wheel("yt_dlp-2026.8.19-py3-none-any.whl"),
            "releases": {
                "2026.8.19": wheel("yt_dlp-2026.8.19-py3-none-any.whl"),
                "2026.10.10.233141.dev0": wheel("yt_dlp-2026.10.10.233141.dev0-py3-none-any.whl"),
                "2026.10.11.1.dev0": [{"packagetype": "sdist", "filename": "x.tar.gz", "url": "u"}],
            },
        }

        class _Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        from core import utils

        monkeypatch.setattr(utils, "safe_requests_get", lambda *a, **k: _Resp())
        version, url, _sha = dc._pypi_latest_wheel("yt-dlp", pre=True)
        assert version == "2026.10.10.233141.dev0"
        assert url.endswith("2026.10.10.233141.dev0-py3-none-any.whl")
        assert dc._pypi_latest_wheel("yt-dlp")[0] == "2026.8.19"

    def test_cli_updates_and_downloads_track_nightly(self):
        assert "yt-dlp-nightly-builds" in dc.YTDLP_LATEST_EXE_URL
        assert "yt-dlp-nightly-builds" in dc._YTDLP_LATEST_API_URL
        assert dc.YTDLP_UPDATE_CHANNEL == "nightly"


class TestVersionHelpers:
    def test_version_key_compares_date_versions(self):
        assert dc._ytdlp_version_key("2026.07.04") == (2026, 7, 4)
        assert dc._ytdlp_version_key("2026.7.4") == (2026, 7, 4)
        assert dc._ytdlp_version_key("2026.07.04") > dc._ytdlp_version_key("2026.06.30")
        assert dc._ytdlp_version_key("") == ()

    def test_read_pkg_version(self, tmp_path):
        pkg = tmp_path / "yt_dlp"
        pkg.mkdir()
        (pkg / "version.py").write_text("__version__ = '2026.07.04'\n", encoding="utf-8")
        assert dc._read_pkg_version(str(pkg)) == "2026.07.04"
        assert dc._read_pkg_version(str(tmp_path / "missing")) == ""


class TestExtractWheelPackage:
    def test_extracts_only_the_package_and_blocks_traversal(self, tmp_path):
        wheel = tmp_path / "yt_dlp-1.whl"
        wheel.write_bytes(
            _make_wheel(
                "yt_dlp",
                version="2099.01.01",
                extra={"../evil.py": "boom", "yt_dlp/sub/mod.py": "x = 1\n"},
            )
        )
        dest = tmp_path / "out"
        dest.mkdir()

        count = dc._extract_wheel_package(str(wheel), "yt_dlp", str(dest))

        assert count == 3  # __init__.py, version.py, sub/mod.py
        assert (dest / "yt_dlp" / "version.py").is_file()
        assert (dest / "yt_dlp" / "sub" / "mod.py").is_file()
        assert not (dest / "README.md").exists()
        assert not (tmp_path / "evil.py").exists()


@pytest.fixture
def frozen_env(tmp_path, monkeypatch):
    """Pretend to be a frozen build with a temp runtime package dir."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    pkg_dir = str(tmp_path / "yt-dlp-module")
    monkeypatch.setattr(dc, "_ytdlp_runtime_pkg_dir", lambda: pkg_dir)
    return pkg_dir


class TestPreferUpdatedYtdlpModule:
    def _seed_managed(self, pkg_dir, version):
        pkg = os.path.join(pkg_dir, "yt_dlp")
        os.makedirs(pkg, exist_ok=True)
        with open(os.path.join(pkg, "__init__.py"), "w") as f:
            f.write("# pkg\n")
        with open(os.path.join(pkg, "version.py"), "w") as f:
            f.write(f"__version__ = '{version}'\n")

    def test_newer_managed_copy_is_put_on_sys_path(
        self, frozen_env, monkeypatch
    ):
        self._seed_managed(frozen_env, "2099.01.01")
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        monkeypatch.delitem(sys.modules, "yt_dlp", raising=False)
        try:
            assert dc.prefer_updated_ytdlp_module() is True
            assert sys.path[0] == frozen_env
        finally:
            if frozen_env in sys.path:
                sys.path.remove(frozen_env)

    def test_older_or_equal_managed_copy_is_ignored(
        self, frozen_env, monkeypatch
    ):
        self._seed_managed(frozen_env, "2026.07.04")
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        assert dc.prefer_updated_ytdlp_module() is False
        assert frozen_env not in sys.path

    def test_missing_managed_copy_is_ignored(self, frozen_env, monkeypatch):
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        assert dc.prefer_updated_ytdlp_module() is False

    def test_unknown_bundled_version_keeps_bundled(
        self, frozen_env, monkeypatch
    ):
        self._seed_managed(frozen_env, "2099.01.01")
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "")
        assert dc.prefer_updated_ytdlp_module() is False
        assert frozen_env not in sys.path

    def test_noop_when_not_frozen(self, frozen_env, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert dc.prefer_updated_ytdlp_module() is False


class TestEnsureYtdlpModuleUpdated:
    def test_downloads_and_installs_newer_wheels(self, frozen_env, monkeypatch):
        wheels = {
            "yt-dlp": ("2099.01.01", _make_wheel("yt_dlp", version="2099.01.01")),
            "yt-dlp-ejs": ("0.3.0", _make_wheel("yt_dlp_ejs")),
        }
        monkeypatch.setattr(dc, "_should_check_updates", lambda *a, **k: True)
        marked = []
        monkeypatch.setattr(dc, "_mark_update_checked", lambda name: marked.append(name))
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        monkeypatch.setattr(
            dc,
            "_pypi_latest_wheel",
            lambda name, timeout=15, **k: (wheels[name][0], f"https://x/{name}.whl", ""),
        )

        def fake_download(url, dest):
            name = url.rsplit("/", 1)[-1].removesuffix(".whl")
            with open(dest, "wb") as f:
                f.write(wheels[name][1])
            return True

        monkeypatch.setattr(dc, "_download_file", fake_download)

        dc.ensure_ytdlp_module_updated()

        version_file = os.path.join(frozen_env, "yt_dlp", "version.py")
        assert os.path.isfile(version_file)
        with open(version_file, encoding="utf-8") as f:
            assert "2099.01.01" in f.read()
        assert os.path.isfile(os.path.join(frozen_env, "yt_dlp_ejs", "__init__.py"))
        assert marked == ["ytdlp_module_update_nightly"]
        # No staging leftovers.
        assert not os.path.exists(frozen_env + ".new")

    def test_current_version_marks_checked_without_download(
        self, frozen_env, monkeypatch
    ):
        monkeypatch.setattr(dc, "_should_check_updates", lambda *a, **k: True)
        marked = []
        monkeypatch.setattr(dc, "_mark_update_checked", lambda name: marked.append(name))
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        monkeypatch.setattr(
            dc,
            "_pypi_latest_wheel",
            lambda name, timeout=15, **k: ("2026.07.04", "https://x/y.whl", ""),
        )

        def fail_download(url, dest):
            raise AssertionError("must not download when already current")

        monkeypatch.setattr(dc, "_download_file", fail_download)

        dc.ensure_ytdlp_module_updated()

        assert marked == ["ytdlp_module_update_nightly"]
        assert not os.path.exists(frozen_env)

    def test_failed_update_does_not_burn_the_throttle_window(
        self, frozen_env, monkeypatch
    ):
        monkeypatch.setattr(dc, "_should_check_updates", lambda *a, **k: True)
        marked = []
        monkeypatch.setattr(dc, "_mark_update_checked", lambda name: marked.append(name))
        monkeypatch.setattr(dc, "_installed_dist_version", lambda _n: "2026.07.04")
        # PyPI unreachable -> no info -> no update, no marker.
        monkeypatch.setattr(dc, "_pypi_latest_wheel", lambda name, timeout=15, **k: None)

        dc.ensure_ytdlp_module_updated()

        assert marked == []
        assert not os.path.exists(frozen_env)

    def test_noop_when_not_frozen(self, frozen_env, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(
            dc,
            "_should_check_updates",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")),
        )
        dc.ensure_ytdlp_module_updated()
