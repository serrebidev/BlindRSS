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
