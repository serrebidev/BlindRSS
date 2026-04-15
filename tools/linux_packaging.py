#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
import textwrap
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "BlindRSS"
PACKAGE_NAME = "blindrss"
PACKAGE_SUMMARY = "BlindRSS feed reader and audio player"
PACKAGE_DESCRIPTION = (
    "BlindRSS is an accessible RSS feed reader and audio player with bundled "
    "media tooling for podcast and article playback."
)
PACKAGE_MAINTAINER = "Brandon <serrebi101@gmail.com>"
PACKAGE_HOMEPAGE = "https://github.com/serrebi/BlindRSS"


@dataclass(frozen=True)
class LinuxArtifactPaths:
    deb: Path
    rpm: Path


def package_architectures(machine: str) -> tuple[str, str]:
    normalized = machine.lower()
    if normalized == "x86_64":
        return ("amd64", "x86_64")
    if normalized in {"aarch64", "arm64"}:
        return ("arm64", "aarch64")
    raise ValueError(f"Unsupported Linux architecture: {machine}")


def artifact_paths(output_dir: Path, version: str, machine: str) -> LinuxArtifactPaths:
    return LinuxArtifactPaths(
        deb=output_dir / f"{APP_NAME}-linux-{machine}-v{version}.deb",
        rpm=output_dir / f"{APP_NAME}-linux-{machine}-v{version}.rpm",
    )


def render_launcher() -> str:
    return textwrap.dedent(
        """\
        #!/bin/sh
        APP_ROOT="/opt/BlindRSS"
        VLC_LIB_DIR="$APP_ROOT/vlc/lib"
        VLC_PLUGIN_DIR="$APP_ROOT/vlc/plugins"
        VLC_LIB_PATH=""

        if [ -d "$VLC_LIB_DIR" ]; then
          for candidate in "$VLC_LIB_DIR"/libvlc.so*; do
            if [ -f "$candidate" ]; then
              VLC_LIB_PATH="$candidate"
              break
            fi
          done
        fi

        export PATH="$APP_ROOT/bin:$PATH"
        export LD_LIBRARY_PATH="$VLC_LIB_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
        if [ -n "$VLC_LIB_PATH" ]; then
          export PYTHON_VLC_LIB_PATH="$VLC_LIB_PATH"
        fi
        if [ -d "$VLC_PLUGIN_DIR" ]; then
          export PYTHON_VLC_MODULE_PATH="$VLC_PLUGIN_DIR"
        fi

        exec "$APP_ROOT/BlindRSS" "$@"
        """
    )


def render_desktop_entry() -> str:
    return textwrap.dedent(
        """\
        [Desktop Entry]
        Type=Application
        Name=BlindRSS
        Comment=BlindRSS feed reader and audio player
        Exec=blindrss
        Icon=BlindRSS
        Terminal=false
        Categories=AudioVideo;News;
        """
    )


def render_debian_control(version: str, deb_arch: str) -> str:
    return textwrap.dedent(
        f"""\
        Package: {PACKAGE_NAME}
        Version: {version}
        Section: sound
        Priority: optional
        Architecture: {deb_arch}
        Maintainer: {PACKAGE_MAINTAINER}
        Homepage: {PACKAGE_HOMEPAGE}
        Description: {PACKAGE_SUMMARY}
         {PACKAGE_DESCRIPTION}
        """
    )


def render_desktop_database_script() -> str:
    return textwrap.dedent(
        """\
        #!/bin/sh
        set -e
        if command -v update-desktop-database >/dev/null 2>&1; then
          update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
        fi
        """
    )


def render_rpm_spec(version: str, rpm_arch: str) -> str:
    return textwrap.dedent(
        f"""\
        %global __strip /bin/true
        %global debug_package %{{nil}}
        %global _build_id_links none

        Name:           {PACKAGE_NAME}
        Version:        {version}
        Release:        1
        Summary:        {PACKAGE_SUMMARY}
        License:        Proprietary
        URL:            {PACKAGE_HOMEPAGE}
        Source0:        %{{name}}-%{{version}}.tar.gz
        BuildArch:      {rpm_arch}
        AutoReqProv:    yes

        %description
        {PACKAGE_DESCRIPTION}

        %prep
        %autosetup

        %build

        %install
        rm -rf %{{buildroot}}
        mkdir -p %{{buildroot}}
        cp -a opt %{{buildroot}}/
        cp -a usr %{{buildroot}}/

        %files
        /opt/BlindRSS
        /usr/bin/blindrss
        /usr/share/applications/blindrss.desktop
        /usr/share/icons/hicolor/scalable/apps/BlindRSS.svg

        %post
        if command -v update-desktop-database >/dev/null 2>&1; then
          update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
        fi

        %postun
        if command -v update-desktop-database >/dev/null 2>&1; then
          update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
        fi
        """
    )


def run_checked(cmd: list[str], *, cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True)


def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f"[X] Required tool not found on PATH: {name}")


def write_text_file(path: Path, content: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def stage_linux_root(bundle_dir: Path, stage_root: Path, icon_source: Path) -> None:
    if not bundle_dir.is_dir():
        raise SystemExit(f"[X] Linux bundle directory not found: {bundle_dir}")
    if not icon_source.is_file():
        raise SystemExit(f"[X] Linux icon not found: {icon_source}")

    if stage_root.exists():
        shutil.rmtree(stage_root)

    app_root = stage_root / "opt" / APP_NAME
    shutil.copytree(bundle_dir, app_root)

    write_text_file(stage_root / "usr" / "bin" / PACKAGE_NAME, render_launcher(), mode=0o755)
    write_text_file(
        stage_root / "usr" / "share" / "applications" / f"{PACKAGE_NAME}.desktop",
        render_desktop_entry(),
    )

    icon_dest = stage_root / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_NAME}.svg"
    icon_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(icon_source, icon_dest)


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def build_deb(stage_root: Path, output_path: Path, version: str, deb_arch: str) -> None:
    require_tool("dpkg-deb")
    deb_root = output_path.parent / "_linux-deb-root"
    copy_tree(stage_root, deb_root)

    write_text_file(deb_root / "DEBIAN" / "control", render_debian_control(version, deb_arch))
    post_script = render_desktop_database_script()
    write_text_file(deb_root / "DEBIAN" / "postinst", post_script, mode=0o755)
    write_text_file(deb_root / "DEBIAN" / "postrm", post_script, mode=0o755)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    run_checked(["dpkg-deb", "--build", "--root-owner-group", str(deb_root), str(output_path)])


def build_rpm(stage_root: Path, output_path: Path, version: str, rpm_arch: str) -> None:
    require_tool("rpmbuild")
    rpmbuild_root = output_path.parent / "_linux-rpmbuild"
    if rpmbuild_root.exists():
        shutil.rmtree(rpmbuild_root)
    for dirname in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
        (rpmbuild_root / dirname).mkdir(parents=True, exist_ok=True)

    source_root = output_path.parent / f"{PACKAGE_NAME}-{version}"
    if source_root.exists():
        shutil.rmtree(source_root)
    source_root.mkdir(parents=True, exist_ok=True)
    for child in stage_root.iterdir():
        destination = source_root / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)

    source_archive = rpmbuild_root / "SOURCES" / f"{PACKAGE_NAME}-{version}.tar.gz"
    with tarfile.open(source_archive, "w:gz") as tar:
        tar.add(source_root, arcname=source_root.name)

    spec_path = rpmbuild_root / "SPECS" / f"{PACKAGE_NAME}.spec"
    write_text_file(spec_path, render_rpm_spec(version, rpm_arch))

    run_checked(
        [
            "rpmbuild",
            "--define",
            f"_topdir {rpmbuild_root}",
            "-bb",
            str(spec_path),
        ]
    )

    built_rpm = next((rpmbuild_root / "RPMS" / rpm_arch).glob("*.rpm"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    shutil.copy2(built_rpm, output_path)


def build_linux_packages(bundle_dir: Path, output_dir: Path, version: str, machine: str, icon_source: Path) -> LinuxArtifactPaths:
    deb_arch, rpm_arch = package_architectures(machine)
    artifacts = artifact_paths(output_dir, version, machine)
    stage_root = output_dir / "_linux-package-root"
    stage_linux_root(bundle_dir, stage_root, icon_source)
    build_deb(stage_root, artifacts.deb, version, deb_arch)
    build_rpm(stage_root, artifacts.rpm, version, rpm_arch)
    return artifacts


def main() -> None:
    parser = argparse.ArgumentParser(description="Build native Linux packages for BlindRSS.")
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--machine", required=True)
    parser.add_argument("--icon-source", required=True, type=Path)
    args = parser.parse_args()

    artifacts = build_linux_packages(
        bundle_dir=args.bundle_dir,
        output_dir=args.output_dir,
        version=args.version,
        machine=args.machine,
        icon_source=args.icon_source,
    )
    print(f"[BlindRSS Build] Created {artifacts.deb}")
    print(f"[BlindRSS Build] Created {artifacts.rpm}")


if __name__ == "__main__":
    main()
