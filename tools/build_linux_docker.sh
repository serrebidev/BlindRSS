#!/usr/bin/env bash
# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_NAME="${BLINDRSS_LINUX_BUILD_IMAGE:-blindrss-linux-builder:ubuntu-22.04}"

if [[ "$(uname -s)" != "Linux" ]]; then
  echo "[X] tools/build_linux_docker.sh must run on a Linux Docker host."
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "[X] Docker was not found on the Linux build host."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "[X] Docker is installed but its daemon is unavailable."
  exit 1
fi

echo "[BlindRSS Linux Build] Preparing the Ubuntu 22.04 builder image..."
docker build --pull --tag "$IMAGE_NAME" --file "$SCRIPT_DIR/linux-build.Dockerfile" "$SCRIPT_DIR"

echo "[BlindRSS Linux Build] Building the self-contained Linux package..."
# The source bind mount and uv cache are different filesystems on the release
# host, so hardlinks cannot work. Select copy mode explicitly instead of making
# uv warn before every otherwise-clean release build.
#
# PyAutoGUI 0.9.54 (an optional SeleniumBase dependency) contains a Linux-only
# ``'\e'`` escape in _pyautogui_x11.py. Limit the filter to that upstream module
# so project SyntaxWarnings and every other warning remain visible.
docker run --rm \
  --env UV_LINK_MODE=copy \
  --env 'PYTHONWARNINGS=ignore:invalid escape sequence:SyntaxWarning:pyautogui._pyautogui_x11' \
  --volume "$REPO_DIR:/src" \
  --workdir /src \
  "$IMAGE_NAME" \
  bash -lc "uv venv --python 3.12 --seed .venv; .venv/bin/python -m pip install --only-binary=:all: https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04/wxpython-4.2.5-cp312-cp312-linux_x86_64.whl; printf 'wxPython==4.2.5\\n' > /tmp/blindrss-linux-constraints.txt; export PIP_CONSTRAINT=/tmp/blindrss-linux-constraints.txt; chmod +x build.sh; ./build.sh build"

mapfile -t archives < <(
  find "$REPO_DIR/dist" -maxdepth 1 -type f -name 'BlindRSS-linux-v*.tar.gz' -print
)
if (( ${#archives[@]} != 1 )); then
  echo "[X] Expected exactly one Linux release tarball, found ${#archives[@]}."
  exit 1
fi
archive="${archives[0]}"
if ! tar -tzf "$archive" BlindRSS/BlindRSS >/dev/null; then
  echo "[X] Linux tarball does not contain the BlindRSS executable."
  exit 1
fi
if ! tar -tzf "$archive" --wildcards 'BlindRSS/_internal/libpython*.so*' >/dev/null; then
  echo "[X] Linux tarball does not contain its bundled Python runtime."
  exit 1
fi

echo "[BlindRSS Linux Build] Verified self-contained artifact: $archive"
