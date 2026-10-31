# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import unittest
import sys
import os
import platform
import tempfile
import threading
from unittest.mock import MagicMock, patch, call

# Mock winreg before importing dependency_check
sys.modules['winreg'] = MagicMock()
import core.dependency_check as dep_check

class TestDependencyLogic(unittest.TestCase):
    def setUp(self):
        dep_check._log = MagicMock()
        self._original_path = os.environ.get("PATH")
        self._original_user_tool_paths = dict(dep_check._USER_TOOL_PATHS)
        dep_check.set_user_tool_paths({})
        # Create a fresh MagicMock for winreg each test and patch it into
        # dep_check directly.  When the full suite runs, other test files may
        # import core.dependency_check before our sys.modules override takes
        # effect, leaving dep_check.winreg bound to the real module.  Patching
        # the attribute ensures the function under test always sees our mock.
        self.mock_winreg = MagicMock()
        self.mock_winreg.HKEY_CURRENT_USER = 1
        self.mock_winreg.KEY_READ = 1
        self.mock_winreg.KEY_SET_VALUE = 2
        self.mock_winreg.REG_EXPAND_SZ = 3
        self.mock_winreg.REG_SZ = 4
        self._winreg_patcher = patch.object(dep_check, 'winreg', self.mock_winreg)
        self._winreg_patcher.start()

    def tearDown(self):
        self._winreg_patcher.stop()
        dep_check.set_user_tool_paths(self._original_user_tool_paths)
        if self._original_path is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = self._original_path
    
    @patch('core.dependency_check._broadcast_env_change')
    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_add_bin_to_user_path_append(self, mock_platform, _mock_broadcast):
        mock_key = MagicMock()
        self.mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        existing_path = r"C:\Existing\Path"
        self.mock_winreg.QueryValueEx.return_value = (existing_path, self.mock_winreg.REG_SZ)
        new_bin = r"C:\New\Bin"
        dep_check._add_bin_to_user_path(new_bin)
        # Windows PATH separator is always ';', regardless of host OS.
        expected_path = existing_path + ";" + new_bin
        self.mock_winreg.SetValueEx.assert_called_with(
            mock_key, "PATH", 0, self.mock_winreg.REG_SZ, expected_path
        )

    @patch('core.dependency_check._broadcast_env_change')
    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_add_bin_to_user_path_empty(self, mock_platform, _mock_broadcast):
        mock_key = MagicMock()
        self.mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        self.mock_winreg.QueryValueEx.side_effect = OSError("Not found")
        new_bin = r"C:\New\Bin"
        dep_check._add_bin_to_user_path(new_bin)
        self.mock_winreg.SetValueEx.assert_called_with(
            mock_key, "PATH", 0, self.mock_winreg.REG_EXPAND_SZ, str(new_bin)
        )

    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_add_bin_to_user_path_already_exists(self, mock_platform):
        mock_key = MagicMock()
        self.mock_winreg.OpenKey.return_value.__enter__.return_value = mock_key
        existing_path = r"C:\Existing\Path;C:\New\Bin"
        self.mock_winreg.QueryValueEx.return_value = (existing_path, self.mock_winreg.REG_SZ)
        self.mock_winreg.QueryValueEx.side_effect = None
        new_bin = r"C:\New\Bin"
        dep_check._add_bin_to_user_path(new_bin)
        self.mock_winreg.SetValueEx.assert_not_called()

    @patch('core.dependency_check.platform.system', return_value='windows')
    @patch('core.dependency_check._has_winget')
    @patch('core.dependency_check._winget_install')
    @patch('core.dependency_check._wait_for_executable')
    @patch('core.dependency_check._ensure_yt_dlp_cli')
    @patch('core.dependency_check._ensure_tool_on_path')
    @patch('core.dependency_check._maybe_add_windows_path')
    def test_install_media_tools_winget_success(self, mock_mawp, mock_etop, mock_dlp_cli, mock_wait, mock_install, mock_has_winget, mock_platform):
        mock_has_winget.return_value = True
        mock_install.return_value = True
        mock_wait.return_value = True # Executable found after install

        dep_check.install_media_tools(vlc=True, ffmpeg=True, ytdlp=True)

        # Verify winget calls
        mock_install.assert_any_call("VideoLAN.VLC", scope="user")
        mock_install.assert_any_call("Gyan.FFmpeg", scope="user")
        mock_install.assert_any_call("yt-dlp.yt-dlp", scope="user")
        
        # Verify wait calls
        mock_wait.assert_any_call("vlc")
        mock_wait.assert_any_call("ffmpeg")
        mock_wait.assert_any_call("yt-dlp")

        # Verify path registration
        mock_etop.assert_any_call("vlc")
        mock_etop.assert_any_call("ffmpeg")
        mock_etop.assert_any_call("yt-dlp")

    @patch('core.dependency_check.platform.system', return_value='windows')
    @patch('core.dependency_check._has_winget')
    @patch('core.dependency_check._winget_install')
    @patch('core.dependency_check._wait_for_executable')
    @patch('core.dependency_check._install_vlc_fallback')
    @patch('core.dependency_check._install_ffmpeg_fallback')
    @patch('core.dependency_check._ensure_yt_dlp_cli')
    @patch('core.dependency_check._ensure_tool_on_path')
    @patch('core.dependency_check._maybe_add_windows_path')
    def test_install_media_tools_fallback_on_fail(self, mock_mawp, mock_etop, mock_dlp_cli, mock_ff_fb, mock_vlc_fb, mock_wait, mock_install, mock_has_winget, mock_platform):
        mock_has_winget.return_value = True
        # Fail winget installs
        mock_install.return_value = False
        # Let fallback installs behave as checks - they return True if they ran (we mock them)
        mock_wait.return_value = True

        dep_check.install_media_tools(vlc=True, ffmpeg=True, ytdlp=True)

        mock_vlc_fb.assert_called_once()
        mock_ff_fb.assert_called_once()
        mock_dlp_cli.assert_called_once()
        
        # Verify path registration still happens
        mock_etop.assert_any_call("vlc")
        mock_etop.assert_any_call("ffmpeg")
        mock_etop.assert_any_call("yt-dlp")

    @patch('core.dependency_check.platform.system', return_value='windows')
    @patch('core.dependency_check._has_winget')
    @patch('core.dependency_check._winget_install')
    @patch('core.dependency_check._wait_for_executable')
    @patch('core.dependency_check._install_vlc_fallback')
    @patch('core.dependency_check._install_ffmpeg_fallback')
    @patch('core.dependency_check._ensure_yt_dlp_cli')
    @patch('core.dependency_check._ensure_tool_on_path')
    @patch('core.dependency_check._maybe_add_windows_path')
    def test_install_media_tools_winget_success_but_exe_missing(
        self,
        mock_mawp,
        mock_etop,
        mock_dlp_cli,
        mock_ff_fb,
        mock_vlc_fb,
        mock_wait,
        mock_install,
        mock_has_winget,
        mock_platform,
    ):
        mock_has_winget.return_value = True
        mock_install.return_value = True
        # Executable NOT found after winget install
        mock_wait.return_value = False

        # We need to control the wait side effect to return True after fallback called?
        # The logic is: winget -> success -> wait(vlc) -> False -> fallback
        # The wait is called AGAIN after fallback in the main flow.
        # So we can set side_effect for wait: [False (winget fail), True (fallback success), False, True, False, True]
        # vlc: wait->False, fallback called, wait->True
        # ffmpeg: wait->False, fallback called, wait->True
        # ytdlp: wait->False, fallback called, wait->True
        mock_wait.side_effect = [False, True, False, True, False, True]

        dep_check.install_media_tools(vlc=True, ffmpeg=True, ytdlp=True)

        mock_vlc_fb.assert_called_once()
        mock_ff_fb.assert_called_once()
        mock_dlp_cli.assert_called_once()

    @patch('core.dependency_check.ensure_media_tools')
    @patch('core.dependency_check._ensure_yt_dlp_cli')
    @patch('core.dependency_check._should_check_updates', return_value=False)
    @patch('core.dependency_check.subprocess.check_call')
    @patch('core.dependency_check.importlib.metadata.distributions')
    def test_check_and_install_dependencies_accepts_webrtcvad_wheels(
        self,
        mock_distributions,
        mock_check_call,
        _mock_should_check_updates,
        _mock_ensure_ytdlp,
        _mock_ensure_media_tools,
    ):
        required = [
            'yt-dlp', 'wxpython', 'feedparser', 'requests', 'beautifulsoup4',
            'python-dateutil', 'mutagen', 'python-vlc',
            'pychromecast', 'async-upnp-client', 'pyatv', 'trafilatura',
            'webrtcvad-wheels', 'brotli', 'html5lib', 'lxml', 'packaging',
        ]

        class FakeDist:
            def __init__(self, name):
                self.name = name
                self.metadata = {"Name": name}

        mock_distributions.return_value = [FakeDist(name) for name in required]

        dep_check.check_and_install_dependencies()

        mock_check_call.assert_not_called()

    @patch('core.dependency_check.platform.system', return_value='darwin')
    @patch('core.dependency_check.shutil.which', return_value=None)
    def test_find_executable_path_uses_macos_frameworks_bin_for_frozen_build(self, _mock_which, _mock_platform):
        with tempfile.TemporaryDirectory() as tmpdir:
            app_dir = os.path.join(tmpdir, "BlindRSS.app", "Contents", "MacOS")
            bin_dir = os.path.join(tmpdir, "BlindRSS.app", "Contents", "Frameworks", "bin")
            os.makedirs(bin_dir, exist_ok=True)
            bundled_tool = os.path.join(bin_dir, "yt-dlp")
            with open(bundled_tool, "w", encoding="utf-8") as handle:
                handle.write("")

            with patch.object(dep_check.sys, "frozen", True, create=True), \
                 patch.object(dep_check.sys, "executable", os.path.join(app_dir, "BlindRSS"), create=True):
                found = dep_check._find_executable_path("yt-dlp")

        self.assertEqual(found, bundled_tool)

    @patch('core.dependency_check._find_executable_path', side_effect=[None, "/tmp/ffmpeg", "/tmp/ffprobe", "/tmp/yt-dlp"])
    @patch('core.dependency_check._candidate_vlc_lib_paths', return_value=["/tmp/libvlc.dylib"])
    @patch('core.dependency_check._maybe_add_windows_path')
    @patch('core.dependency_check.platform.system', return_value='darwin')
    def test_check_media_tools_status_uses_vlc_library_on_macos(
        self,
        _mock_platform,
        _mock_maybe_add_windows_path,
        _mock_candidate_vlc_lib_paths,
        _mock_find_executable_path,
    ):
        with patch("core.dependency_check.os.path.isfile", return_value=False):
            missing_vlc, missing_ffmpeg, missing_ytdlp = dep_check.check_media_tools_status()

        self.assertFalse(missing_vlc)
        self.assertFalse(missing_ffmpeg)
        self.assertFalse(missing_ytdlp)

    def test_user_override_path_takes_priority(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = os.path.join(tmp, "ffmpeg.exe")
            with open(fake, "w", encoding="utf-8") as handle:
                handle.write("")
            try:
                dep_check.set_user_tool_paths({"ffmpeg": fake})
                # Override must win before PATH / package scans even run.
                with patch("core.dependency_check.shutil.which", return_value="/somewhere/else/ffmpeg"):
                    found = dep_check._find_executable_path("ffmpeg")
                self.assertEqual(found, fake)
            finally:
                dep_check.set_user_tool_paths({})

    @patch('core.dependency_check.platform.system', return_value='Windows')
    def test_managed_ytdlp_beats_stale_path_install(self, _mock_platform):
        # The app updates its own copy nightly; a WinGet stable build that
        # _maybe_add_windows_path put first on PATH used to be run instead.
        with tempfile.TemporaryDirectory() as tmp:
            managed = os.path.join(tmp, "yt-dlp.exe")
            with open(managed, "w", encoding="utf-8") as handle:
                handle.write("")
            with patch.object(dep_check, "_managed_ytdlp_exe", managed), \
                 patch.object(dep_check, "_maybe_add_windows_path"), \
                 patch("core.dependency_check.shutil.which", return_value=__file__):
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), managed)
                # A Settings override still beats the managed copy.
                override = os.path.join(tmp, "custom", "yt-dlp.exe")
                os.makedirs(os.path.dirname(override))
                with open(override, "w", encoding="utf-8") as handle:
                    handle.write("")
                dep_check.set_user_tool_paths({"yt-dlp": override})
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), override)
                dep_check.set_user_tool_paths({})
                # Gone from disk, or never verified: PATH as before.
                os.remove(managed)
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), __file__)
            with patch.object(dep_check, "_managed_ytdlp_exe", None), \
                 patch.object(dep_check, "_maybe_add_windows_path"), \
                 patch("core.dependency_check.shutil.which", return_value=__file__):
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), __file__)

    @patch('core.dependency_check._add_bin_to_user_path')
    @patch('core.dependency_check._should_check_updates', return_value=False)
    @patch('core.dependency_check.platform.system', return_value='Windows')
    def test_only_a_working_managed_ytdlp_is_recorded(self, _mock_platform, _mock_updates, _mock_user_path):
        with tempfile.TemporaryDirectory() as tmp:
            local_exe = os.path.join(tmp, "yt-dlp.exe")
            with open(local_exe, "w", encoding="utf-8") as handle:
                handle.write("")
            system_exe = os.path.join(tmp, "winget", "yt-dlp.exe")
            os.makedirs(os.path.dirname(system_exe))
            with open(system_exe, "w", encoding="utf-8") as handle:
                handle.write("")
            working = {local_exe, system_exe}

            def fake_run(cmd, **_kwargs):
                return MagicMock(returncode=0 if cmd[0] in working else 1)

            with patch.object(dep_check, "_managed_ytdlp_exe", None), \
                 patch.object(dep_check, "_ytdlp_runtime_bin_dir", return_value=tmp), \
                 patch.object(dep_check, "_maybe_add_windows_path"), \
                 patch("core.dependency_check.subprocess.run", side_effect=fake_run), \
                 patch("core.dependency_check.shutil.which", return_value=system_exe):
                dep_check._ensure_yt_dlp_cli()
                self.assertEqual(dep_check._managed_ytdlp_exe, local_exe)
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), local_exe)

                # A truncated copy that does not run must not hide the working one.
                dep_check._managed_ytdlp_exe = None
                working.discard(local_exe)
                dep_check._ensure_yt_dlp_cli()
                self.assertIsNone(dep_check._managed_ytdlp_exe)
                self.assertEqual(dep_check._find_executable_path("yt-dlp"), system_exe)

    @patch('core.dependency_check._mark_update_checked')
    @patch('core.dependency_check._add_bin_to_user_path')
    @patch('core.dependency_check._should_check_updates', return_value=True)
    @patch('core.dependency_check.platform.system', return_value='Windows')
    def test_managed_ytdlp_is_used_while_the_update_runs(self, _mock_platform, _mock_updates, _mock_user_path,
                                                          _mock_mark):
        # The nightly update can take minutes on the first launch of a day;
        # lookups meanwhile used to fall back to PATH (WinGet first).
        with tempfile.TemporaryDirectory() as tmp:
            local_exe = os.path.join(tmp, "yt-dlp.exe")
            with open(local_exe, "w", encoding="utf-8") as handle:
                handle.write("")
            seen_during_update = []

            def slow_update(exe, _works):
                seen_during_update.append(dep_check._find_executable_path("yt-dlp"))
                return True

            with patch.object(dep_check, "_managed_ytdlp_exe", None), \
                 patch.object(dep_check, "_ytdlp_runtime_bin_dir", return_value=tmp), \
                 patch.object(dep_check, "_maybe_add_windows_path"), \
                 patch.object(dep_check, "_update_managed_ytdlp", side_effect=slow_update), \
                 patch("core.dependency_check.subprocess.run", return_value=MagicMock(returncode=0)), \
                 patch("core.dependency_check.shutil.which", return_value=__file__):
                dep_check._ensure_yt_dlp_cli()
            self.assertEqual(seen_during_update, [local_exe])

    def test_resolved_ytdlp_cli_is_logged_once_per_path(self):
        from core import discovery

        with patch.object(discovery, "_logged_ytdlp_cli_path", None), \
             patch.object(dep_check, "_find_executable_path", return_value=r"C:\winget\yt-dlp.exe") as find, \
             self.assertLogs("core.discovery", level="DEBUG") as logs:
            discovery._resolve_ytdlp_cli_path()
            discovery._resolve_ytdlp_cli_path()
            find.return_value = r"C:\app\bin\yt-dlp.exe"
            discovery._resolve_ytdlp_cli_path()
        self.assertEqual(
            logs.output,
            [
                r"DEBUG:core.discovery:yt-dlp CLI: C:\winget\yt-dlp.exe",
                r"DEBUG:core.discovery:yt-dlp CLI: C:\app\bin\yt-dlp.exe",
            ],
        )

    def test_user_override_directory_resolves_executable(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Create both names so the test is platform-agnostic.
            for name in ("yt-dlp", "yt-dlp.exe"):
                with open(os.path.join(tmp, name), "w", encoding="utf-8") as handle:
                    handle.write("")
            try:
                dep_check.set_user_tool_paths({"yt-dlp": tmp})
                found = dep_check._find_executable_path("yt-dlp")
                self.assertIsNotNone(found)
                self.assertTrue(os.path.basename(found).startswith("yt-dlp"))
            finally:
                dep_check.set_user_tool_paths({})

    def test_set_user_tool_paths_ignores_blank_values(self):
        dep_check.set_user_tool_paths({"ffmpeg": "", "yt-dlp": "  ", "ffprobe": r"C:\x\ffprobe.exe"})
        try:
            self.assertEqual(dep_check._USER_TOOL_PATHS, {"ffprobe": r"C:\x\ffprobe.exe"})
        finally:
            dep_check.set_user_tool_paths({})

    def test_ffprobe_shares_ffmpeg_candidate_dirs(self):
        ffmpeg_dirs, _ = dep_check._collect_tool_candidates("ffmpeg")
        ffprobe_dirs, _ = dep_check._collect_tool_candidates("ffprobe")
        # ffprobe ships beside ffmpeg, so it must search the same Gyan/manual dirs.
        self.assertIn(r"C:\ffmpeg\bin", ffprobe_dirs)
        self.assertTrue(any("Gyan" in d and "FFmpeg" in d for d in ffprobe_dirs))
        self.assertIn(r"C:\ffmpeg\bin", ffmpeg_dirs)

    def test_expand_path_globs(self):
        with tempfile.TemporaryDirectory() as tmp:
            versioned = os.path.join(tmp, "ffmpeg-7.1", "bin")
            os.makedirs(versioned, exist_ok=True)
            pattern = os.path.join(tmp, "ffmpeg-*", "bin")
            out = dep_check._expand_path_globs([pattern])
            self.assertIn(versioned, out)
            # Non-glob paths pass through unchanged.
            self.assertIn(tmp, dep_check._expand_path_globs([tmp]))

    @patch("core.dependency_check.subprocess.run")
    def test_validate_executable_version_args(self, mock_run):
        with tempfile.TemporaryDirectory() as tmp:
            exe = os.path.join(tmp, "tool")
            with open(exe, "w", encoding="utf-8") as handle:
                handle.write("")
            mock_run.return_value = MagicMock(returncode=0)
            self.assertTrue(dep_check._validate_executable(exe, tool="ffmpeg"))
            self.assertEqual(mock_run.call_args[0][0][1], "-version")
            self.assertTrue(dep_check._validate_executable(exe, tool="yt-dlp"))
            self.assertEqual(mock_run.call_args[0][0][1], "--version")
            mock_run.return_value = MagicMock(returncode=1)
            self.assertFalse(dep_check._validate_executable(exe, tool="ffprobe"))

    def test_validate_executable_missing_file(self):
        self.assertFalse(dep_check._validate_executable(r"C:\nope\ffmpeg.exe", tool="ffmpeg"))

    @patch("core.dependency_check._maybe_add_windows_path")
    @patch("core.dependency_check._validate_executable", return_value=True)
    @patch("core.dependency_check._find_executable_path")
    def test_detect_media_tool_paths_passes_ffmpeg_dir_to_ffprobe(self, mock_find, _mock_val, _mawp):
        resolved = {
            "ffmpeg": r"C:\ff\ffmpeg.exe",
            "ffprobe": r"C:\ff\ffprobe.exe",
            "yt-dlp": r"C:\y\yt-dlp.exe",
        }
        mock_find.side_effect = lambda name, extra_dirs=None: resolved[dep_check._canon_tool_name(name)]
        res = dep_check.detect_media_tool_paths()
        self.assertEqual(res["ffmpeg"]["path"], r"C:\ff\ffmpeg.exe")
        self.assertTrue(res["ffprobe"]["valid"])
        extras = {
            dep_check._canon_tool_name(c.args[0]): c.kwargs.get("extra_dirs")
            for c in mock_find.call_args_list
        }
        # ffprobe detection should be told to look beside the found ffmpeg first.
        self.assertEqual(extras["ffprobe"], [r"C:\ff"])

    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_windows_path_search_runs_once_unless_forced(self, _mock_platform):
        # Every yt-dlp/ffmpeg lookup and silence scan calls this; it used to
        # redo the whole registry/disk scan each time (log spam during playback).
        def searches():
            return sum(1 for c in dep_check._log.call_args_list
                       if "meticulous Windows path search" in str(c.args[0]))

        with patch.object(dep_check, "_windows_path_searched", False), \
             patch.dict(os.environ, {"LOCALAPPDATA": "", "USERPROFILE": ""}), \
             patch.object(os, "add_dll_directory", MagicMock(), create=True):
            dep_check._maybe_add_windows_path()
            dep_check._maybe_add_windows_path()
            dep_check._maybe_add_windows_path()
            self.assertEqual(searches(), 1)
            dep_check._maybe_add_windows_path(force=True)
            self.assertEqual(searches(), 2)

    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_concurrent_first_calls_share_one_windows_path_search(self, _mock_platform):
        # Startup ran two scans at once: the flag is only set after a full pass.
        started, release, scans = threading.Event(), threading.Event(), []

        def slow_scan():
            scans.append(1)
            started.set()
            release.wait(5)

        with patch.object(dep_check, "_windows_path_searched", False), \
             patch.object(dep_check, "_scan_windows_path", side_effect=slow_scan):
            first = threading.Thread(target=dep_check._maybe_add_windows_path)
            first.start()
            self.assertTrue(started.wait(5))
            second = threading.Thread(target=dep_check._maybe_add_windows_path)
            second.start()
            second.join(0.2)  # let it reach the check while the first scan runs
            release.set()
            first.join(5)
            second.join(5)
        self.assertEqual(len(scans), 1)

if __name__ == '__main__':
    unittest.main()
