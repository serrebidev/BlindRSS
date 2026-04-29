import json
import os
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


if __name__ == "__main__":
    unittest.main()
