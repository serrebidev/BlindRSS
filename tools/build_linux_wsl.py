# Copyright (c) serrebidev and contributors
# SPDX-License-Identifier: MIT
"""Build Linux in the default WSL distribution without publishing or versioning."""

import argparse
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parents[1]
WSL = ["wsl.exe", "--user", "root", "--exec"]
BUILD = r'''
set -euo pipefail
build_root="$HOME/.cache/blindrss-builds"
mkdir -p "$build_root"
build_dir="$(mktemp -d "$build_root/build-XXXXXX")"
cleanup() {
    case "$build_dir" in
        "$build_root"/build-??????) rm -rf -- "$build_dir" ;;
        *) echo "Refusing unsafe build cleanup" >&2; return 1 ;;
    esac
}
trap 'cleanup || exit 1' EXIT
mkdir "$build_dir/source"
tar -xf "$1" -C "$build_dir/source"
cd "$build_dir/source"
bash tools/build_linux_docker.sh
archives=(dist/BlindRSS-linux-v*.tar.gz)
[ "${#archives[@]}" = 1 ] && [ -f "${archives[0]}" ]
cp -- "${archives[0]}" "$2/"
'''


def write_snapshot(repo, output, ref=None):
    if ref:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--verify", "--end-of-options", ref + "^{commit}"], cwd=repo
        ).decode().strip()
        with open(output, "wb") as stream:
            subprocess.run(["git", "archive", "--format=tar", commit], cwd=repo, stdout=stream, check=True)
    else:
        names = subprocess.check_output(["git", "ls-files", "-z"], cwd=repo).decode("utf-8").split("\0")
        with tarfile.open(output, "w") as archive:
            for name in filter(None, names):
                path = Path(repo) / name
                if path.exists() or path.is_symlink():
                    archive.add(path, arcname=name, recursive=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="Check WSL Docker without building")
    parser.add_argument("--ref", help="Build an exact Git ref; default uses tracked working files, including staged additions")
    args = parser.parse_args()
    subprocess.run(WSL + ["sh", "-c", "command -v docker >/dev/null && docker info >/dev/null"], check=True)
    if args.verify:
        print("WSL Docker builder is ready.")
        return
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    descriptor, snapshot = tempfile.mkstemp(prefix="blindrss-linux-", suffix=".tar")
    os.close(descriptor)
    try:
        write_snapshot(ROOT, snapshot, args.ref)
        paths = [subprocess.check_output(WSL + ["wslpath", "-a", "-u", str(path)]).decode().strip()
                 for path in (snapshot, output)]
        subprocess.run(WSL + ["bash", "-c", BUILD, "blindrss-linux-build", *paths], check=True)
    finally:
        Path(snapshot).unlink(missing_ok=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Linux WSL build failed: {exc}")
