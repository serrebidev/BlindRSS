# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import zipfile

from tools import build_utils


def test_zip_directory_streams_one_top_level_tree(tmp_path):
    source = tmp_path / "BlindRSS"
    (source / "_internal").mkdir(parents=True)
    (source / "BlindRSS.exe").write_bytes(b"exe")
    (source / "_internal" / "module.bin").write_bytes(b"payload")
    destination = tmp_path / "BlindRSS.zip"

    build_utils.zip_directory(source, destination)

    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == {
            "BlindRSS/BlindRSS.exe",
            "BlindRSS/_internal/module.bin",
        }
        assert archive.read("BlindRSS/_internal/module.bin") == b"payload"
    assert not (tmp_path / "BlindRSS.zip.tmp").exists()


def _version_node(key, value=b"", children=b"", kind=1, value_len=None):
    import struct

    head = (key + "\0").encode("utf-16-le")
    body = head + b"\0" * (-(6 + len(head)) % 4) + value
    body += b"\0" * (-(6 + len(body)) % 4) + children
    if value_len is None:
        value_len = len(value) // 2 if kind == 1 else len(value)
    return struct.pack("<HHH", 6 + len(body), value_len, kind) + body


def _version_string(key, text):
    node = _version_node(key, (text + "\0").encode("utf-16-le"))
    return node + b"\0" * (-len(node) % 4)


def test_trim_version_strings_removes_inno_padding_without_moving_bytes(tmp_path):
    from tools.build_utils import trim_version_strings

    strings = (
        _version_string("CompanyName", "Serrebi".ljust(60))
        + _version_string("ProductName", "BlindRSS".ljust(60))
        + _version_string("ProductVersion", "2.1.1".ljust(20))
        + _version_string("LegalCopyright", "")
    )
    table = _version_node("000004b0", children=strings)
    info = _version_node("StringFileInfo", children=table)
    var = _version_node("VarFileInfo", children=_version_node("Translation", b"\x00\x00\xb0\x04", kind=0), kind=1)
    root = _version_node("VS_VERSION_INFO", b"\xbd\x04\xef\xfe" + b"\0" * 48, info + var, kind=0)
    exe = tmp_path / "Setup.exe"
    original = b"MZ" + b"\x90" * 30 + root + b"payload after the resource"
    exe.write_bytes(original)

    assert trim_version_strings(exe) == 3
    patched = exe.read_bytes()
    assert len(patched) == len(original)
    assert patched.endswith(b"payload after the resource") and patched[:32] == original[:32]
    for name, want in (("ProductName", "BlindRSS"), ("ProductVersion", "2.1.1"), ("CompanyName", "Serrebi")):
        at = patched.index((name + "\0").encode("utf-16-le"))
        value_at = at + len(name) * 2 + 2
        value_at += -(value_at - 32) % 4
        text = patched[value_at:value_at + 130].decode("utf-16-le", "ignore")
        assert text.split("\0")[0] == want
        assert int.from_bytes(patched[at - 4:at - 2], "little") == len(want) + 1
    # Already clean: nothing to do, file untouched.
    assert trim_version_strings(exe) == 0 and exe.read_bytes() == patched


def test_installer_build_trims_version_strings_before_signing():
    import pathlib

    bat = (pathlib.Path(__file__).resolve().parents[1] / "build.bat").read_text(encoding="utf-8")
    block = bat[bat.index("\n:build_installer\n"):bat.index("\n:sign_installer\n")]
    assert "trim-version-strings" in block
