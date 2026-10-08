# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import argparse
import hashlib
import os
import re
import struct
import subprocess
import zipfile
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


def zip_directory(input_dir: Path, output_path: Path) -> None:
    """Create a streaming ZIP containing ``input_dir`` as its top-level dir."""
    source = input_dir.resolve(strict=True)
    if not source.is_dir():
        raise SystemExit(f"ZIP input is not a directory: {source}")
    destination = output_path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".tmp")
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(source.name) / path.relative_to(source))
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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


_VERSION_INFO_KEY = "VS_VERSION_INFO\0".encode("utf-16-le")


def _align4(n: int) -> int:
    return (n + 3) & ~3


def _trim_version_node(buf: bytearray, pos: int) -> int:
    """Trim space padding from every string under the version node at ``pos``.

    Returns how many strings changed. Nothing moves: a trimmed value is
    NUL-filled to its old width and only its wValueLength is rewritten.
    """
    length, value_len, kind = struct.unpack_from("<HHH", buf, pos)
    end = pos + length
    key_end = buf.find(b"\0\0", pos + 6, end)
    while key_end != -1 and (key_end - pos) % 2:  # NUL must sit on a UTF-16 boundary
        key_end = buf.find(b"\0\0", key_end + 1, end)
    if length < 8 or key_end == -1:
        raise ValueError(f"malformed version resource node at offset {pos}")
    value_pos = pos + _align4(key_end + 2 - pos)
    if kind == 1 and value_len:  # a String: its value fills the rest of the node
        text = buf[value_pos:end].decode("utf-16-le").split("\0")[0]
        trimmed = text.rstrip(" ")
        if trimmed == text:
            return 0
        buf[value_pos:end] = trimmed.encode("utf-16-le").ljust(end - value_pos, b"\0")
        struct.pack_into("<H", buf, pos + 2, len(trimmed) + 1)
        return 1
    changed = 0
    child = value_pos + _align4(value_len)
    while child + 6 <= end:
        changed += _trim_version_node(buf, child)
        child += _align4(struct.unpack_from("<H", buf, child)[0])
    return changed


def trim_version_strings(exe_path: Path) -> int:
    """Remove the space padding Inno Setup leaves in an installer's version strings.

    Inno Setup writes ProductName, ProductVersion and the rest over fixed-width,
    space-filled slots, so the installer reports its product name as "BlindRSS"
    followed by 52 spaces. SignPath compares the product name and version
    exactly and refuses that. Edited in place so no file offset changes, which
    the installer's own offset table depends on.
    """
    buf = bytearray(exe_path.read_bytes())
    changed = 0
    found = buf.find(_VERSION_INFO_KEY)
    if found == -1:
        raise ValueError(f"{exe_path} has no version resource")
    while found != -1:
        changed += _trim_version_node(buf, found - 6)
        found = buf.find(_VERSION_INFO_KEY, found + len(_VERSION_INFO_KEY))
    if changed:
        exe_path.write_bytes(buf)
    return changed


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

    p_zip = sub.add_parser("zip-directory", help="Create a streaming ZIP archive")
    p_zip.add_argument("--input", required=True)
    p_zip.add_argument("--output", required=True)

    p_sig = sub.add_parser("signtool-thumbprint", help="Extract signing thumbprint via signtool verify")
    p_sig.add_argument("--signtool", required=True)
    p_sig.add_argument("--exe", required=True)
    p_sig.add_argument("--output")

    p_trim = sub.add_parser("trim-version-strings", help="Strip Inno Setup's space padding from version strings")
    p_trim.add_argument("--exe", required=True)

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
        case "zip-directory":
            zip_directory(Path(args.input), Path(args.output))
        case "trim-version-strings":
            print(f"Trimmed {trim_version_strings(Path(args.exe))} version string(s) in {args.exe}")
        case "signtool-thumbprint":
            _write_output(signtool_thumbprint(Path(args.signtool), Path(args.exe)))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
