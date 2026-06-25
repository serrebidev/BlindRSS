import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class UpdaterLaunchTests(unittest.TestCase):
    def test_launch_update_helper_uses_helper_directory_as_cwd(self) -> None:
        from core import updater

        helper_dir = tempfile.mkdtemp(prefix="blindrss_helper_test_")
        helper_path = os.path.join(helper_dir, "update_helper.bat")
        try:
            with open(helper_path, "w", encoding="utf-8") as f:
                f.write("@echo off\n")

            with patch("core.updater.subprocess.Popen", return_value=MagicMock()) as popen:
                ok, msg = updater._launch_update_helper(helper_path, 1234, r"C:\Install", r"C:\Stage")
                self.assertTrue(ok, msg)
                _args, kwargs = popen.call_args
                self.assertEqual(kwargs.get("cwd"), helper_dir)
        finally:
            try:
                import shutil

                shutil.rmtree(helper_dir, ignore_errors=True)
            except Exception:
                pass

    def test_launch_update_helper_stays_hidden_even_in_debug_mode(self) -> None:
        from core import updater

        class FakeStartupInfo:
            def __init__(self) -> None:
                self.dwFlags = 0
                self.wShowWindow = None

        helper_dir = tempfile.mkdtemp(prefix="blindrss_helper_test_")
        helper_path = os.path.join(helper_dir, "update_helper.bat")
        try:
            with open(helper_path, "w", encoding="utf-8") as f:
                f.write("@echo off\n")

            with (
                patch.object(updater.sys, "platform", "win32"),
                patch("core.updater.subprocess.STARTUPINFO", FakeStartupInfo, create=True),
                patch("core.updater.subprocess.STARTF_USESHOWWINDOW", 1, create=True),
                patch("core.updater.subprocess.CREATE_BREAKAWAY_FROM_JOB", 0x01000000, create=True),
                patch("core.updater.subprocess.Popen", return_value=MagicMock()) as popen,
            ):
                ok, msg = updater._launch_update_helper(
                    helper_path,
                    1234,
                    r"C:\Install",
                    r"C:\Stage",
                    debug_mode=True,
                )

            self.assertTrue(ok, msg)
            args, kwargs = popen.call_args
            cmd = args[0]
            self.assertEqual(cmd[1:3], ["/d", "/c"])
            self.assertNotIn("start", [str(part).lower() for part in cmd])
            self.assertTrue(kwargs.get("creationflags") & 0x08000000)
            self.assertIs(kwargs.get("stdin"), updater.subprocess.DEVNULL)
            self.assertIs(kwargs.get("stdout"), updater.subprocess.DEVNULL)
            self.assertIs(kwargs.get("stderr"), updater.subprocess.DEVNULL)
        finally:
            try:
                import shutil

                shutil.rmtree(helper_dir, ignore_errors=True)
            except Exception:
                pass

    def test_launch_update_helper_supports_installer_mode(self) -> None:
        from core import updater

        helper_dir = tempfile.mkdtemp(prefix="blindrss_helper_test_")
        helper_path = os.path.join(helper_dir, "update_helper.bat")
        try:
            with open(helper_path, "w", encoding="utf-8") as f:
                f.write("@echo off\n")

            with patch("core.updater.subprocess.Popen", return_value=MagicMock()) as popen:
                ok, msg = updater._launch_update_helper(
                    helper_path,
                    1234,
                    r"C:\Install",
                    "",
                    temp_root=r"C:\Temp\BlindRSS_update_1",
                    installer_path=r"C:\Temp\BlindRSS-Setup-v2.0.0.exe",
                )

            self.assertTrue(ok, msg)
            cmd = popen.call_args.args[0]
            self.assertEqual(cmd[4], "--installer")
            self.assertEqual(cmd[5], "1234")
            self.assertEqual(cmd[6], r"C:\Install")
            self.assertEqual(cmd[7], r"C:\Temp\BlindRSS-Setup-v2.0.0.exe")
        finally:
            import shutil

            shutil.rmtree(helper_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

