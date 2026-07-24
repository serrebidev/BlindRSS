# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import argparse
import hashlib
import re
import subprocess
from pathlib import Path


def _extract_requirement_name(line: str):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    if stripped.startswith(("-", "--")):
        return None
    m = re.match(r"^([A-Za-z0-9_.-]+)", stripped)
    return (m.group(1).lower() if m else None)


def filter_requirements(input_path: Path, output_path: Path, exclude: list[str]):
    exclude = {e.lower() for e in (exclude or []) if e}
    if not exclude:
        raise SystemExit("No excluded package names provided.")

    lines = input_path.read_text(encoding="utf-8").splitlines()
    kept = []
    for line in lines:
        name = _extract_requirement_name(line)
        if name and name in exclude:
            continue
        kept.append(line)
    output_path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def sha256_file(input_path: Path) -> str:
    h = hashlib.sha256()
    with input_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def signtool_thumbprint(signtool_exe: Path, exe_path: Path) -> str:
    result = subprocess.run(
        [str(signtool_exe), "verify", "/pa", "/v", str(exe_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    data = (result.stdout or "") + (result.stderr or "")
    m = re.search(r"SHA1 hash:\s*([0-9A-Fa-f]{40})", data)
    return (m.group(1).strip().replace(" ", "") if m else "")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_filter = sub.add_parser("filter-requirements", help="Write a filtered requirements.txt")
    p_filter.add_argument("--input", required=True)
    p_filter.add_argument("--output", required=True)
    p_filter.add_argument("--exclude", action="append", default=[])

    p_hash = sub.add_parser("sha256", help="Compute SHA-256 of a file")
    p_hash.add_argument("--input", required=True)
    p_hash.add_argument("--output")

    p_sig = sub.add_parser("signtool-thumbprint", help="Extract signing thumbprint via signtool verify")
    p_sig.add_argument("--signtool", required=True)
    p_sig.add_argument("--exe", required=True)
    p_sig.add_argument("--output")

    args = parser.parse_args()

    def _write_output(digest: str) -> None:
        if args.output:
            Path(args.output).write_text(digest, encoding="utf-8")
        else:
            print(digest)

    match args.cmd:
        case "filter-requirements":
            filter_requirements(Path(args.input), Path(args.output), args.exclude)
        case "sha256":
            _write_output(sha256_file(Path(args.input)))
        case "signtool-thumbprint":
            _write_output(signtool_thumbprint(Path(args.signtool), Path(args.exe)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
