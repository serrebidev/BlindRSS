import json
from datetime import datetime

import pytest

from tools import release


# --- version parsing / formatting -------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("v1.2.3", (1, 2, 3)),
        ("1.2.3", (1, 2, 3)),
        ("1.2", (1, 2, 0)),       # missing patch defaults to 0
        ("  v1.68.0  ", (1, 68, 0)),  # surrounding whitespace is stripped
        ("1.02.3", (1, 2, 3)),    # leading zeros parse as ints
    ],
)
def test_parse_version_accepts_valid_forms(value, expected):
    assert release.parse_version(value) == expected


@pytest.mark.parametrize("value", ["", None, "v2", "1", "1.2.3.4", "abc", "v1.x"])
def test_parse_version_rejects_invalid_forms(value):
    assert release.parse_version(value) is None


def test_format_version_and_tag():
    assert release.format_version((1, 68, 0)) == "1.68.0"
    assert release.format_tag((1, 68, 0)) == "v1.68.0"


# --- conventional-commit classification --------------------------------------


@pytest.mark.parametrize(
    "subject, body",
    [
        ("feat!: drop python 3.13", ""),
        ("refactor: cleanup", "BREAKING CHANGE: config moved"),
        ("chore: thing !: weird", ""),
    ],
)
def test_is_breaking_detects_breaking_changes(subject, body):
    full = f"{subject}\n{body}".strip()
    assert release.is_breaking(subject, body, full) is True


def test_is_breaking_false_for_normal_commits():
    assert release.is_breaking("feat: add casting", "", "feat: add casting") is False
    assert release.is_breaking("fix: typo", "", "fix: typo") is False


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("feat: add chromecast", True),
        ("feat(player): handoff", True),
        ("add a nice feature", True),
        ("fix: crash", False),
        ("chore: deps", False),
    ],
)
def test_is_feature(subject, expected):
    assert release.is_feature(subject, "", subject) is expected


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("fix: crash on cast", True),
        ("fixup logging", True),
        ("resolve bug in parser", True),
        ("feat: new ui", False),
        ("docs: readme", False),
    ],
)
def test_is_fix(subject, expected):
    assert release.is_fix(subject, "", subject) is expected


# --- bump decision -----------------------------------------------------------


def _commit(subject, body=""):
    full = f"{subject}\n{body}".strip()
    return (subject, body, full)


def test_decide_bump_prioritizes_breaking_over_feature():
    commits = [_commit("feat: first"), _commit("api!: removed")]
    assert release.decide_bump(commits) == "major"


def test_decide_bump_feature_when_no_breaking():
    commits = [_commit("fix: a"), _commit("feat: b")]
    assert release.decide_bump(commits) == "minor"


def test_decide_bump_patch_for_fixes_and_chores_only():
    assert release.decide_bump([_commit("fix: a"), _commit("chore: b")]) == "patch"
    assert release.decide_bump([]) == "patch"


@pytest.mark.parametrize(
    "bump, expected",
    [
        ("major", (2, 0, 0)),
        ("minor", (1, 3, 0)),
        ("patch", (1, 2, 4)),
    ],
)
def test_bump_version(bump, expected):
    assert release.bump_version((1, 2, 3), bump) == expected


# --- compute_next_version (git calls monkeypatched) --------------------------


def test_compute_next_version_minor_bump(monkeypatch):
    monkeypatch.setattr(release, "get_latest_tag", lambda: "v1.68.0")
    monkeypatch.setattr(release, "get_commits_since", lambda *_: [_commit("feat: x")])

    # Returns (latest_tag, base_version, next_version, bump, commits).
    info = release.compute_next_version()

    assert info[0] == "v1.68.0"
    assert info[1] == (1, 68, 0)
    assert info[2] == (1, 69, 0)
    assert info[3] == "minor"


def test_compute_next_version_patch_bump(monkeypatch):
    monkeypatch.setattr(release, "get_latest_tag", lambda: "v1.68.0")
    monkeypatch.setattr(release, "get_commits_since", lambda *_: [_commit("fix: y")])

    info = release.compute_next_version()

    assert info[2] == (1, 68, 1)
    assert info[3] == "patch"


def test_compute_next_version_clamps_to_minimum(monkeypatch):
    monkeypatch.setattr(release, "get_latest_tag", lambda: "v1.0.0")
    monkeypatch.setattr(release, "get_commits_since", lambda *_: [_commit("fix: y")])

    info = release.compute_next_version()

    # (1, 0, 1) is below MINIMUM_VERSION, so it is raised to the floor.
    assert info[2] == release.MINIMUM_VERSION


def test_compute_next_version_seeds_when_no_tag(monkeypatch):
    monkeypatch.setattr(release, "get_latest_tag", lambda: None)
    monkeypatch.setattr(release, "get_commits_since", lambda *_: [])

    info = release.compute_next_version()

    assert info[0] == ""
    assert info[1] is None
    assert info[3] == "seed"
    assert info[2] == release.MINIMUM_VERSION  # seed (1,4,2) clamped to the floor


# --- version file read/write -------------------------------------------------


def test_read_current_version_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "VERSION_FILE", str(tmp_path / "version.py"))
    assert release.read_current_version() is None


def test_write_then_read_version_round_trip(tmp_path, monkeypatch):
    version_file = tmp_path / "version.py"
    version_file.write_text('APP_VERSION = "1.0.0"\n', encoding="utf-8")
    monkeypatch.setattr(release, "VERSION_FILE", str(version_file))

    release.write_version("1.68.1")

    assert release.read_current_version() == "1.68.1"
    assert 'APP_VERSION = "1.68.1"' in version_file.read_text(encoding="utf-8")


def test_write_version_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "VERSION_FILE", str(tmp_path / "absent.py"))
    with pytest.raises(RuntimeError, match="Version file not found"):
        release.write_version("1.2.3")


def test_write_version_without_app_version_marker_raises(tmp_path, monkeypatch):
    version_file = tmp_path / "version.py"
    version_file.write_text("SOMETHING_ELSE = 1\n", encoding="utf-8")
    monkeypatch.setattr(release, "VERSION_FILE", str(version_file))

    with pytest.raises(RuntimeError, match="Failed to update APP_VERSION"):
        release.write_version("1.2.3")


# --- release notes / summary -------------------------------------------------


def test_build_summary_orders_sections_and_handles_empty():
    summary = release.build_summary(["api!: x"], ["feat: y"], ["fix: z"])
    assert summary == "Breaking: api!: x | Feature: feat: y | Fix: fix: z"
    assert release.build_summary([], [], []) == "Maintenance update."


def test_build_summary_truncates_long_text():
    summary = release.build_summary(["B" * 250], [], [])
    assert len(summary) <= 200
    assert summary.endswith("...")


def test_build_release_notes_sections_and_placeholders():
    commits = [
        _commit("feat: add casting"),
        _commit("fix: crash"),
        _commit("docs: tidy readme"),
    ]
    notes, summary = release.build_release_notes("v1.68.1", commits)

    assert notes.startswith("# BlindRSS v1.68.1")
    assert "## Breaking\n- None" in notes
    assert "- feat: add casting" in notes
    assert "- fix: crash" in notes
    assert "- docs: tidy readme" in notes  # falls into the Other bucket
    assert summary == "Feature: feat: add casting | Fix: fix: crash"


# --- manifest generation -----------------------------------------------------


def test_write_manifest_minimal_omits_optional_fields(tmp_path):
    output = tmp_path / "BlindRSS-update.json"
    release.write_manifest(
        "v1.68.1",
        "BlindRSS-v1.68.1.zip",
        "a" * 64,
        "",  # no notes summary
        str(output),
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))

    assert manifest["version"] == "v1.68.1"
    assert manifest["asset"] == "BlindRSS-v1.68.1.zip"
    assert manifest["sha256"] == "a" * 64
    assert manifest["download_url"].endswith("/v1.68.1/BlindRSS-v1.68.1.zip")
    # Optional fields are absent when not supplied.
    assert "notes_summary" not in manifest
    assert "signing_thumbprint" not in manifest
    assert "installer" not in manifest
    # published_at is an ISO-8601 timestamp.
    datetime.fromisoformat(manifest["published_at"])


def test_write_manifest_omits_installer_when_only_one_half_supplied(tmp_path):
    output = tmp_path / "BlindRSS-update.json"
    release.write_manifest(
        "v1.68.1",
        "BlindRSS-v1.68.1.zip",
        "a" * 64,
        "Summary.",
        str(output),
        installer_asset_name="BlindRSS-Setup-v1.68.1.exe",
        # installer_sha256 intentionally omitted
    )

    manifest = json.loads(output.read_text(encoding="utf-8"))

    assert manifest["notes_summary"] == "Summary."
    assert "installer" not in manifest
