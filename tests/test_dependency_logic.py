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

    @patch('core.dependency_check._find_executable_path', side_effect=[None, "/tmp/ffmpeg", "/tmp/yt-dlp"])
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

if __name__ == '__main__':
    unittest.main()
