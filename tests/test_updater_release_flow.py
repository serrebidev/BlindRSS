# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


class UpdaterReleaseFlowTests(unittest.TestCase):
    def test_latest_release_request_uses_current_repo_owner(self) -> None:
        from core import updater

        response = MagicMock()
        response.status_code = 200
        response.ok = True
        response.json.return_value = {"tag_name": "v1.2.3", "assets": []}

        with patch("core.updater.safe_requests_get", return_value=response) as get:
            release, err = updater._fetch_latest_release()

        self.assertIsNone(err)
        self.assertEqual(release["tag_name"], "v1.2.3")
        url = get.call_args.args[0]
        self.assertEqual(url, "https://api.github.com/repos/serrebidev/BlindRSS/releases/latest")

    def test_manifest_generation_uses_current_repo_owner(self) -> None:
        from tools.release import write_manifest

        with tempfile.TemporaryDirectory(prefix="blindrss_manifest_test_") as tmp:
            output = os.path.join(tmp, "BlindRSS-update.json")
            write_manifest(
                "v9.8.7",
                "BlindRSS-v9.8.7.zip",
                "a" * 64,
                "Test summary.",
                output,
                signing_thumbprint="12 34",
                installer_asset_name="BlindRSS-Setup-v9.8.7.exe",
                installer_sha256="c" * 64,
            )

            with open(output, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        self.assertEqual(manifest["version"], "v9.8.7")
        self.assertEqual(manifest["asset"], "BlindRSS-v9.8.7.zip")
        self.assertEqual(
            manifest["download_url"],
            "https://github.com/serrebidev/BlindRSS/releases/download/v9.8.7/BlindRSS-v9.8.7.zip",
        )
        self.assertEqual(manifest["sha256"], "a" * 64)
        self.assertEqual(manifest["signing_thumbprint"], "12 34")
        self.assertEqual(manifest["installer"]["asset"], "BlindRSS-Setup-v9.8.7.exe")
        self.assertEqual(manifest["installer"]["sha256"], "c" * 64)
        self.assertEqual(
            manifest["installer"]["download_url"],
            "https://github.com/serrebidev/BlindRSS/releases/download/"
            "v9.8.7/BlindRSS-Setup-v9.8.7.exe",
        )

    def test_check_for_updates_accepts_release_manifest_and_zip_assets(self) -> None:
        from core import updater

        release = {
            "tag_name": "v9.8.7",
            "published_at": "2026-04-29T00:00:00Z",
            "assets": [
                {
                    "name": "BlindRSS-update.json",
                    "browser_download_url": "https://github.com/assets/manifest",
                },
                {
                    "name": "BlindRSS-v9.8.7.zip",
                    "browser_download_url": "https://github.com/assets/zip",
                },
            ],
        }
        manifest = {
            "version": "v9.8.7",
            "asset": "BlindRSS-v9.8.7.zip",
            "download_url": "https://github.com/serrebidev/BlindRSS/releases/download/v9.8.7/BlindRSS-v9.8.7.zip",
            "sha256": "b" * 64,
            "notes_summary": "Test update.",
            "signing_thumbprint": "aa bb cc",
        }

        with patch("core.updater.APP_VERSION", "1.0.0"):
            with patch("core.updater._fetch_latest_release", return_value=(release, None)):
                with patch("core.updater.current_platform", return_value="windows"):
                    with patch("core.updater._download_json", return_value=(manifest, None)) as download_json:
                        result = updater.check_for_updates()

        self.assertEqual(result.status, "update_available")
        self.assertIsNotNone(result.info)
        self.assertEqual(download_json.call_args.args[0], "https://github.com/assets/manifest")
        self.assertEqual(result.info.tag, "v9.8.7")
        self.assertEqual(result.info.asset_name, "BlindRSS-v9.8.7.zip")
        self.assertEqual(result.info.download_url, "https://github.com/assets/zip")
        self.assertEqual(result.info.sha256, "b" * 64)
        self.assertEqual(result.info.signing_thumbprints, ("AABBCC",))
        self.assertEqual(result.info.asset_kind, "archive")

    def test_installed_windows_build_selects_installer_asset(self) -> None:
        from core import updater

        release = {
            "tag_name": "v9.8.7",
            "published_at": "2026-04-29T00:00:00Z",
            "assets": [
                {
                    "name": "BlindRSS-update.json",
                    "browser_download_url": "https://github.com/assets/manifest",
                },
                {
                    "name": "BlindRSS-v9.8.7.zip",
                    "browser_download_url": "https://github.com/assets/zip",
                },
                {
                    "name": "BlindRSS-Setup-v9.8.7.exe",
                    "browser_download_url": "https://github.com/assets/setup",
                },
            ],
        }
        manifest = {
            "version": "v9.8.7",
            "asset": "BlindRSS-v9.8.7.zip",
            "sha256": "b" * 64,
            "installer": {
                "asset": "BlindRSS-Setup-v9.8.7.exe",
                "sha256": "c" * 64,
            },
        }

        with patch("core.updater.APP_VERSION", "1.0.0"):
            with patch("core.updater._fetch_latest_release", return_value=(release, None)):
                with patch("core.updater.current_platform", return_value="windows"):
                    with patch("core.updater.is_windows_installed_build", return_value=True):
                        with patch("core.updater._download_json", return_value=(manifest, None)):
                            result = updater.check_for_updates()

        self.assertEqual(result.status, "update_available")
        self.assertIsNotNone(result.info)
        self.assertEqual(result.info.asset_name, "BlindRSS-Setup-v9.8.7.exe")
        self.assertEqual(result.info.download_url, "https://github.com/assets/setup")
        self.assertEqual(result.info.sha256, "c" * 64)
        self.assertEqual(result.info.asset_kind, "installer")

    def test_authenticode_verification_tries_next_powershell(self) -> None:
        from core import updater

        failed = MagicMock()
        failed.returncode = 1
        failed.stderr = "Get-AuthenticodeSignature not found"
        failed.stdout = ""

        succeeded = MagicMock()
        succeeded.returncode = 0
        succeeded.stderr = ""
        succeeded.stdout = json.dumps(
            {
                "Status": "UnknownError",
                "StatusMessage": "Self-signed certificate.",
                "Subject": "CN=BlindRSS Dev",
                "Thumbprint": "aa bb cc",
            }
        )

        with patch("core.updater._powershell_executables", return_value=("bad-powershell", "pwsh")):
            with patch("core.updater.subprocess.run", side_effect=(failed, succeeded)) as run:
                ok, msg = updater._verify_authenticode_signature("BlindRSS.exe", ["AABBCC"])

        self.assertTrue(ok, msg)
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0][0], "bad-powershell")
        self.assertEqual(run.call_args_list[1].args[0][0], "pwsh")

    def test_pinned_thumbprint_never_accepts_a_tampered_file(self) -> None:
        from core import updater

        for status in ("HashMismatch", "NotSigned", "NotSupportedFileFormat", "Incompatible"):
            result = MagicMock(returncode=0, stderr="")
            result.stdout = json.dumps(
                {"Status": status, "StatusMessage": "", "Subject": "CN=BlindRSS Dev", "Thumbprint": "aabbcc"}
            )
            with patch("core.updater._powershell_executables", return_value=("pwsh",)):
                with patch("core.updater.subprocess.run", return_value=result):
                    ok, _msg = updater._verify_authenticode_signature("BlindRSS.exe", ["AABBCC"])
            self.assertFalse(ok, status)

    def test_authenticode_reads_localized_status_message_as_utf8(self) -> None:
        # Regression: Windows localizes StatusMessage. On a Polish Windows
        # (ANSI code page 1250) the text could not be decoded, stdout came back
        # empty and every update failed although the pinned signer matched.
        from core import updater

        text = json.dumps(
            {
                "Status": "UnknownError",
                "StatusMessage": "Łańcuch certyfikatów został przetworzony, ale operację "
                "przerwano na certyfikacie głównym.",
                "Subject": "CN=BlindRSS Dev",
                "Thumbprint": "AABBCC",
            },
            ensure_ascii=False,
        )
        real_run = subprocess.run
        # UTF-8 as requested; cp852 (OEM) when PowerShell refuses the change,
        # e.g. in constrained language mode.
        for encoding in ("utf-8", "cp852"):
            payload = text.encode(encoding)
            scripts = []

            def run_child(cmd, **kwargs):
                # A real process, so the caller's arguments decide how its bytes decode.
                scripts.append(cmd[-1])
                child = "import sys; sys.stdout.buffer.write(bytes.fromhex(sys.argv[1]))"
                return real_run([sys.executable, "-c", child, payload.hex()], **kwargs)

            with patch("locale.getencoding", return_value="cp1250"):
                with patch("core.updater._powershell_executables", return_value=("powershell",)):
                    with patch("core.updater.subprocess.run", side_effect=run_child):
                        ok, msg = updater._verify_authenticode_signature("BlindRSS-Setup.exe", ["AABBCC"])

            self.assertTrue(ok, f"{encoding}: {msg}")
            self.assertTrue(scripts[0].startswith("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"))

    def test_authenticode_check_hides_the_powershell_console(self) -> None:
        # The app is windowed: without CREATE_NO_WINDOW each check opened a
        # console window that could take focus from a screen reader.
        from core import updater

        result = MagicMock(returncode=0, stderr="")
        result.stdout = json.dumps({"Status": "Valid", "StatusMessage": "", "Subject": "", "Thumbprint": "AABBCC"})
        with patch("core.updater._powershell_executables", return_value=("powershell",)):
            with patch("core.updater.subprocess.run", return_value=result) as run:
                ok, msg = updater._verify_authenticode_signature("BlindRSS-Setup.exe", ["AABBCC"])

        self.assertTrue(ok, msg)
        flags = run.call_args.kwargs.get("creationflags", 0)
        if sys.platform == "win32":
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
        else:
            self.assertEqual(flags, 0)


if __name__ == "__main__":
    unittest.main()
