import unittest
import sys
import os
import platform
import tempfile
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
    
    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_add_bin_to_user_path_append(self, mock_platform):
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

    @patch('core.dependency_check.platform.system', return_value='windows')
    def test_add_bin_to_user_path_empty(self, mock_platform):
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
    @patch('core.dependency_check._ensure_tool_on_path')
    @patch('core.dependency_check._maybe_add_windows_path')
    def test_install_media_tools_winget_success(self, mock_mawp, mock_etop, mock_wait, mock_install, mock_has_winget, mock_platform):
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
    def test_install_media_tools_winget_success_but_exe_missing(self, mock_dlp_cli, mock_ff_fb, mock_vlc_fb, mock_wait, mock_install, mock_has_winget, mock_platform):
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

if __name__ == '__main__':
    unittest.main()
