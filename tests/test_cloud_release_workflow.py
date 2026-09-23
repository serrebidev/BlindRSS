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
    publish = wf["jobs"]["publish"]
    assert publish["if"] == "${{ !inputs.dry_run }}"
    assert set(publish["needs"]) == {"prepare", "build"}
    assert wf["jobs"]["build"]["with"]["publish_assets"] == "${{ !inputs.dry_run }}"


def test_cloud_release_verifies_every_asset_before_publishing_latest():
    steps = _load("cloud-release.yml")["jobs"]["publish"]["steps"]
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
    assert {"release_tag", "ref", "build_windows", "build_linux", "publish_assets"} <= set(call_inputs)
    for job in ("windows", "macos", "linux"):
        for step in wf["jobs"][job]["steps"]:
            if "gh release upload" in str(step.get("run", "")):
                assert "inputs.publish_assets" in step["if"], (job, step["name"])
    win = [s["name"] for s in wf["jobs"]["windows"]["steps"]]
    assert win.index("Verify Authenticode signatures") < win.index("Upload release assets")
