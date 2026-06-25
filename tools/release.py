import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from core.update_config import GITHUB_OWNER, GITHUB_REPO

VERSION_FILE = os.path.join(ROOT, "core", "version.py")
APP_NAME = "BlindRSS"

SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")
MINIMUM_VERSION = (1, 42, 0)


def run_git(args):
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {msg}")
    return result.stdout


def parse_version(value):
    if not value:
        return None
    m = SEMVER_RE.match(str(value).strip())
    if not m:
        return None
    major, minor, patch = m.groups()
    return (int(major), int(minor), int(patch or 0))


def format_version(version):
    return f"{version[0]}.{version[1]}.{version[2]}"


def format_tag(version):
    return f"v{format_version(version)}"


def get_latest_tag():
    try:
        tag = run_git(["describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"]).strip()
        if parse_version(tag):
            return tag
    except Exception:
        pass

    try:
        tags = run_git(["tag", "--merged"]).splitlines()
    except Exception:
        return None

    best_tag = None
    best_version = None
    for tag in tags:
        tag = tag.strip()
        version = parse_version(tag)
        if not version:
            continue
        if best_version is None or version > best_version:
            best_version = version
            best_tag = tag
    return best_tag


def get_commits_since(tag):
    if tag:
        rev = f"{tag}..HEAD"
        args = ["log", rev, "--pretty=format:%s%n%b%x00"]
    else:
        args = ["log", "--pretty=format:%s%n%b%x00"]
    raw = run_git(args)
    commits = []
    for block in raw.split("\x00"):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        subject = lines[0].strip() if lines else ""
        body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        commits.append((subject, body, block))
    return commits


def is_breaking(subject, body, full):
    if re.search(r"BREAKING CHANGE", full, re.IGNORECASE):
        return True
    if re.match(r"^[a-zA-Z]+!:", subject):
        return True
    if "!:" in subject:
        return True
    return False


def is_feature(subject, _body, _full):
    s = subject.lower()
    return s.startswith("feat") or "feature" in s


def is_fix(subject, _body, _full):
    s = subject.lower()
    return s.startswith("fix") or "fix" in s or "bug" in s


def decide_bump(commits):
    for subject, body, full in commits:
        if is_breaking(subject, body, full):
            return "major"
    for subject, body, full in commits:
        if is_feature(subject, body, full):
            return "minor"
    return "patch"


def bump_version(base, bump):
    major, minor, patch = base
    if bump == "major":
        return (major + 1, 0, 0)
    if bump == "minor":
        return (major, minor + 1, 0)
    return (major, minor, patch + 1)


def compute_next_version():
    latest_tag = get_latest_tag()
    base_version = parse_version(latest_tag) if latest_tag else None
    commits = get_commits_since(latest_tag)

    if not base_version:
        next_version = (1, 4, 2)
        bump = "seed"
    else:
        bump = decide_bump(commits)
        next_version = bump_version(base_version, bump)

    if next_version < MINIMUM_VERSION:
        next_version = MINIMUM_VERSION

    return latest_tag or "", base_version, next_version, bump, commits


def read_current_version():
    if not os.path.isfile(VERSION_FILE):
        return None
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        return None
    return m.group(1)


def write_version(new_version):
    if not os.path.isfile(VERSION_FILE):
        raise RuntimeError(f"Version file not found: {VERSION_FILE}")
    with open(VERSION_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    updated, count = re.subn(
        r'APP_VERSION\s*=\s*["\']([^"\']+)["\']',
        f'APP_VERSION = "{new_version}"',
        content,
        count=1,
    )
    if count != 1:
        raise RuntimeError("Failed to update APP_VERSION in core/version.py")
    with open(VERSION_FILE, "w", encoding="utf-8") as f:
        f.write(updated)


def build_release_notes(tag, commits):
    breaking = []
    features = []
    fixes = []
    other = []

    for subject, body, full in commits:
        if is_breaking(subject, body, full):
            breaking.append(subject)
        elif is_feature(subject, body, full):
            features.append(subject)
        elif is_fix(subject, body, full):
            fixes.append(subject)
        else:
            other.append(subject)

    lines = [f"# {APP_NAME} {tag}", ""]

    def add_section(title, items):
        lines.append(f"## {title}")
        if items:
            for item in items:
                lines.append(f"- {item}")
        else:
            lines.append("- None")
        lines.append("")

    add_section("Breaking", breaking)
    add_section("Features", features)
    add_section("Fixes", fixes)
    add_section("Other", other)

    summary = build_summary(breaking, features, fixes)
    return "\n".join(lines).strip() + "\n", summary


def build_summary(breaking, features, fixes):
    parts = []
    if breaking:
        parts.append(f"Breaking: {breaking[0]}")
    if features:
        parts.append(f"Feature: {features[0]}")
    if fixes:
        parts.append(f"Fix: {fixes[0]}")
    if not parts:
        return "Maintenance update."
    summary = " | ".join(parts)
    if len(summary) > 200:
        summary = summary[:197].rstrip() + "..."
    return summary


def write_manifest(
    version_tag,
    asset_name,
    sha256,
    notes_summary,
    output_path,
    signing_thumbprint=None,
    installer_asset_name=None,
    installer_sha256=None,
):
    download_url = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{version_tag}/{asset_name}"
    manifest = {
        "version": version_tag,
        "asset": asset_name,
        "download_url": download_url,
        "sha256": sha256,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }
    if notes_summary:
        manifest["notes_summary"] = notes_summary
    if signing_thumbprint:
        manifest["signing_thumbprint"] = signing_thumbprint
    if installer_asset_name and installer_sha256:
        manifest["installer"] = {
            "asset": installer_asset_name,
            "download_url": (
                f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/"
                f"{version_tag}/{installer_asset_name}"
            ),
            "sha256": installer_sha256,
        }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def cmd_next_version(_args):
    latest_tag, _base_version, next_version, bump, _commits = compute_next_version()
    print(f"LATEST_TAG={latest_tag}")
    print(f"NEXT_VERSION={format_version(next_version)}")
    print(f"NEXT_TAG={format_tag(next_version)}")
    print(f"BUMP={bump}")


def cmd_current_version(_args):
    current = read_current_version()
    if current is None:
        raise RuntimeError("Unable to read current version.")
    print(f"CURRENT_VERSION={current}")


def cmd_bump_version(args):
    write_version(args.version)
    print(f"UPDATED_VERSION={args.version}")


def cmd_write_notes(args):
    commits = get_commits_since(args.from_tag)
    notes, summary = build_release_notes(args.to_tag, commits)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(notes)
    if args.summary_output:
        with open(args.summary_output, "w", encoding="utf-8") as f:
            f.write(summary)
    print(f"NOTES_FILE={args.output}")
    print(f"NOTES_SUMMARY={summary}")


def cmd_write_manifest(args):
    notes_summary = ""
    if args.notes_summary_file:
        if os.path.isfile(args.notes_summary_file):
            with open(args.notes_summary_file, "r", encoding="utf-8") as f:
                notes_summary = f.read().strip()
    write_manifest(
        args.version_tag,
        args.asset_name,
        args.sha256,
        notes_summary,
        args.output,
        signing_thumbprint=args.signing_thumbprint,
        installer_asset_name=args.installer_asset_name,
        installer_sha256=args.installer_sha256,
    )
    print(f"MANIFEST_FILE={args.output}")


def main():
    parser = argparse.ArgumentParser(description="BlindRSS release helper")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    subparsers.add_parser("next-version")
    subparsers.add_parser("current-version")

    bump = subparsers.add_parser("bump-version")
    bump.add_argument("--version", required=True)

    notes = subparsers.add_parser("write-notes")
    notes.add_argument("--from-tag", default="")
    notes.add_argument("--to-tag", required=True)
    notes.add_argument("--output", required=True)
    notes.add_argument("--summary-output")

    manifest = subparsers.add_parser("write-manifest")
    manifest.add_argument("--version-tag", required=True)
    manifest.add_argument("--asset-name", required=True)
    manifest.add_argument("--sha256", required=True)
    manifest.add_argument("--output", required=True)
    manifest.add_argument("--notes-summary-file")
    manifest.add_argument("--signing-thumbprint")
    manifest.add_argument("--installer-asset-name")
    manifest.add_argument("--installer-sha256")

    args = parser.parse_args()

    if args.cmd == "next-version":
        cmd_next_version(args)
    elif args.cmd == "current-version":
        cmd_current_version(args)
    elif args.cmd == "bump-version":
        cmd_bump_version(args)
    elif args.cmd == "write-notes":
        cmd_write_notes(args)
    elif args.cmd == "write-manifest":
        cmd_write_manifest(args)
    else:
        raise RuntimeError(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
