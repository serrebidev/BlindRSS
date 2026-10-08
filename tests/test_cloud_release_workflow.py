# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Static guards for the GitHub-runner release path (cloud-release.yml).

The updater only sees a published, Latest release, so the cloud path must keep
the release a draft until every platform has uploaded, and a dry run must never
push, tag or publish.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def _load(name):
    data = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # PyYAML reads the bare key `on` as boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def test_cloud_release_defaults_to_dry_run_and_serializes():
    wf = _load("cloud-release.yml")
    dry = wf["on"]["workflow_dispatch"]["inputs"]["dry_run"]
    assert dry["type"] == "boolean" and dry["default"] is True
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_cloud_release_pushes_and_publishes_only_for_real_runs():
    wf = _load("cloud-release.yml")
    prepare = {s["name"]: s for s in wf["jobs"]["prepare"]["steps"]}
    tag_step = prepare["Commit, tag and create draft release"]
    assert tag_step["if"] == "${{ !inputs.dry_run }}"
    assert "--draft" in tag_step["run"] and "git push --atomic" in tag_step["run"]
    build = wf["jobs"]["build"]["with"]
    assert build["publish_assets"] == "${{ !inputs.dry_run }}"
    assert build["publish_release"] == "${{ !inputs.dry_run }}"
    # A dry run must never spend a release signature.
    assert build["signing_policy"] == "${{ inputs.dry_run && 'test-signing' || 'release-signing' }}"


def test_release_verifies_every_asset_before_publishing_latest():
    publish = _load("cross-platform-release.yml")["jobs"]["publish"]
    assert set(publish["needs"]) == {"windows", "macos", "linux"}
    assert "inputs.publish_release" in publish["if"] and "failure" in publish["if"]
    steps = publish["steps"]
    names = [s["name"] for s in steps]
    assert names.index("Verify every platform uploaded its assets") < names.index("Publish as Latest")
    verify = steps[0]["run"]
    for asset in (
        "BlindRSS-v$v.zip", "BlindRSS-Setup-v$v.exe", "BlindRSS-update.json",
        "BlindRSS-linux-v$v.tar.gz", "BlindRSS-update-linux.json",
        "BlindRSS-macos-v$v.zip", "BlindRSS-update-macos.json",
    ):
        assert asset in verify
    assert "--draft=false --latest" in steps[1]["run"]
    assert "releases/latest" in steps[2]["run"]


def test_cloud_release_builds_all_platforms_with_signing_secrets():
    build = _load("cloud-release.yml")["jobs"]["build"]
    assert build["uses"] == "./.github/workflows/cross-platform-release.yml"
    assert build["with"]["build_windows"] is True and build["with"]["build_linux"] is True
    assert build["secrets"] == "inherit"


def test_cross_platform_workflow_is_reusable_and_gates_uploads():
    wf = _load("cross-platform-release.yml")
    call_inputs = wf["on"]["workflow_call"]["inputs"]
    assert {"release_tag", "ref", "build_windows", "build_linux", "publish_assets",
            "publish_release", "signing_policy"} <= set(call_inputs)
    for job in ("windows", "macos", "linux"):
        for step in wf["jobs"][job]["steps"]:
            if "gh release upload" in str(step.get("run", "")):
                assert "inputs.publish_assets" in step["if"], (job, step["name"])
    win = [s["name"] for s in wf["jobs"]["windows"]["steps"]]
    assert win.index("Verify Authenticode signatures") < win.index("Upload release assets")


def test_windows_is_signed_by_signpath_exe_first_then_installer():
    wf = _load("cross-platform-release.yml")
    steps = wf["jobs"]["windows"]["steps"]
    names = [s["name"] for s in steps]
    order = ["Build application", "Sign executable with SignPath",
             "Package ZIP and installer around the signed executable",
             "Sign installer with SignPath", "Verify Authenticode signatures",
             "Install the signed installer silently", "Upload release assets"]
    assert [names.index(n) for n in order] == sorted(names.index(n) for n in order)
    for step in steps:
        if "signpath/" in str(step.get("uses", "")):
            assert step["with"]["signing-policy-slug"] == "${{ inputs.signing_policy }}"
            assert step["with"]["api-token"] == "${{ secrets.SIGNPATH_API_TOKEN }}"
    # No certificate or private key ever reaches the repository or a runner.
    text = (WORKFLOWS / "cross-platform-release.yml").read_text(encoding="utf-8")
    assert "PFX" not in text and "signtool" not in text.lower()


def test_local_release_never_builds_or_signs_windows():
    bat = (ROOT / "build.bat").read_text(encoding="utf-8")
    release = bat[bat.index('if /I "%MODE%"=="release" ('):bat.index(") else (\n    call :compute_current_version")]
    for call in ("build_app", "sign_exe", "sign_installer", "build_installer"):
        assert f"call :{call}" not in release
    assert "call :dispatch_ci_release" in release
    assert "--draft --verify-tag" in bat and "signing_policy=release-signing" in bat


def test_cloud_caller_grants_what_the_signing_job_needs():
    # A called workflow can only keep or reduce its caller's permissions.
    called = _load("cross-platform-release.yml")["permissions"]
    caller = _load("cloud-release.yml")["permissions"]
    assert called == caller == {"contents": "write", "actions": "read"}


def test_dispatch_block_parentheses_balance():
    bat = (ROOT / "build.bat").read_text(encoding="utf-8")
    block = bat[bat.index("\n:dispatch_ci_release\n"):bat.index("\n:done")]
    depth = 0
    for line in block.splitlines():
        if line.startswith(("echo ", "rem ", "set ")):
            continue
        depth += line.rstrip().endswith("(") - (line.strip() == ")")
        assert depth >= 0, line
    assert depth == 0
