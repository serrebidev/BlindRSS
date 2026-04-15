#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-build}"
RELEASE_TAG="${2:-${BLINDRSS_RELEASE_TAG:-}}"
case "$MODE" in
  build|dry-run|release) ;;
  *)
    echo "Usage: ./build.sh <build|dry-run|release> [release-tag]"
    exit 1
    ;;
esac

UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"

case "$UNAME_S" in
  Darwin)
    YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"
    case "$UNAME_M" in
      arm64|aarch64) DENO_ASSET="deno-aarch64-apple-darwin.zip" ;;
      x86_64) DENO_ASSET="deno-x86_64-apple-darwin.zip" ;;
      *)
        echo "[X] Unsupported macOS architecture: $UNAME_M"
        exit 1
        ;;
    esac
    ;;
  *)
    echo "[X] build.sh currently supports macOS only. Unsupported platform: $UNAME_S"
    exit 1
    ;;
esac

detect_python() {
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_EXE="$(command -v python3)"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    PYTHON_EXE="$(command -v python)"
    return 0
  fi
  echo "[X] python3/python not found."
  exit 1
}

setup_venv() {
  detect_python
  VENV_DIR="$SCRIPT_DIR/.venv"
  if [[ ! -x "$VENV_DIR/bin/python" ]]; then
    echo "[BlindRSS Build] Creating virtualenv..."
    "$PYTHON_EXE" -m venv "$VENV_DIR"
  fi

  VENV_PYTHON="$VENV_DIR/bin/python"
  echo "[BlindRSS Build] Updating build tools..."
  "$VENV_PYTHON" -m pip install --upgrade pip
  "$VENV_PYTHON" -m pip install --upgrade pyinstaller packaging

  echo "[BlindRSS Build] Installing dependencies from requirements.txt..."
  if ! "$VENV_PYTHON" -m pip install -r requirements.txt; then
    echo "[WARN] Dependency installation failed. Retrying without webrtcvad packages."
    local req_tmp
    req_tmp="$(mktemp)"
    "$VENV_PYTHON" tools/build_utils.py filter-requirements \
      --input requirements.txt \
      --output "$req_tmp" \
      --exclude webrtcvad \
      --exclude webrtcvad-wheels
    "$VENV_PYTHON" -m pip install -r "$req_tmp"
    rm -f "$req_tmp"
  fi
}

ensure_bin_dir() {
  mkdir -p "$SCRIPT_DIR/bin"
}

download_file() {
  local url="$1"
  local dest="$2"
  curl -L --fail --retry 3 --retry-delay 2 -o "$dest" "$url"
}

ensure_yt_dlp() {
  ensure_bin_dir
  local dest="$SCRIPT_DIR/bin/yt-dlp"
  echo "[BlindRSS Build] Ensuring yt-dlp binary is present..."
  download_file "$YTDLP_URL" "$dest"
  chmod +x "$dest"
}

ensure_deno() {
  ensure_bin_dir
  local dest="$SCRIPT_DIR/bin/deno"
  local tmp_dir zip_path
  tmp_dir="$(mktemp -d)"
  zip_path="$tmp_dir/deno.zip"
  echo "[BlindRSS Build] Ensuring Deno binary is present..."
  download_file "https://github.com/denoland/deno/releases/latest/download/$DENO_ASSET" "$zip_path"
  unzip -o -j "$zip_path" deno -d "$tmp_dir" >/dev/null
  mv "$tmp_dir/deno" "$dest"
  chmod +x "$dest"
  rm -rf "$tmp_dir"
}

ensure_ffmpeg() {
  ensure_bin_dir
  local ffmpeg_path
  local dest="$SCRIPT_DIR/bin/ffmpeg"
  ffmpeg_path="$(command -v ffmpeg || true)"
  if [[ -z "$ffmpeg_path" && -x "$(command -v brew || true)" ]]; then
    echo "[BlindRSS Build] ffmpeg missing. Installing with Homebrew..."
    brew install ffmpeg
    ffmpeg_path="$(command -v ffmpeg || true)"
  fi
  if [[ -z "$ffmpeg_path" ]]; then
    echo "[X] ffmpeg not found on PATH."
    exit 1
  fi
  rm -f "$dest"
  install -m 755 "$ffmpeg_path" "$dest"
}

ensure_vlc_macos() {
  local vlc_app="${BLINDRSS_VLC_APP:-/Applications/VLC.app}"
  if [[ ! -d "$vlc_app" ]]; then
    echo "[X] VLC.app not found at $vlc_app"
    echo "[X] Install VLC or set BLINDRSS_VLC_APP to the app bundle path."
    exit 1
  fi
  export BLINDRSS_VLC_APP="$vlc_app"
}

dispatch_macos_release_workflow() {
  local release_tag="$1"
  if [[ -z "$release_tag" ]]; then
    echo "[X] ./build.sh release requires an existing GitHub release tag."
    echo "[X] Usage: ./build.sh release vX.Y.Z"
    exit 1
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "[X] GitHub CLI (gh) not found on PATH."
    exit 1
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "[X] gh is not authenticated."
    exit 1
  fi
  if ! gh release view "$release_tag" >/dev/null 2>&1; then
    echo "[X] GitHub release $release_tag was not found in this repository."
    echo "[X] Create the Windows release first with .\\build.bat release."
    exit 1
  fi
  echo "[BlindRSS Build] Dispatching GitHub macOS release workflow for $release_tag..."
  gh workflow run cross-platform-release.yml -f release_tag="$release_tag"
  echo "[BlindRSS Build] Workflow dispatched."
  echo "[BlindRSS Build] GitHub Actions will build the macOS ZIP and upload it to release $release_tag."
}

read_version() {
  VERSION_NO_V="$("$SCRIPT_DIR/.venv/bin/python" - <<'PY'
from core.version import APP_VERSION
print(APP_VERSION)
PY
)"
}

build_pyinstaller() {
  read_version
  rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/dist"
  export BLINDRSS_APP_VERSION="$VERSION_NO_V"
  echo "[BlindRSS Build] Running PyInstaller (portable.spec)..."
  "$SCRIPT_DIR/.venv/bin/python" -m PyInstaller --clean --noconfirm portable.spec
}

package_macos() {
  local app_path="$SCRIPT_DIR/dist/BlindRSS.app"
  local zip_path="$SCRIPT_DIR/dist/BlindRSS-macos-v${VERSION_NO_V}.zip"
  local identity="${BLINDRSS_CODESIGN_IDENTITY:--}"
  if [[ "${BLINDRSS_SKIP_MACOS_CODESIGN:-0}" != "1" ]]; then
    if ! command -v codesign >/dev/null 2>&1; then
      echo "[X] codesign not found on PATH."
      exit 1
    fi
    echo "[BlindRSS Build] Codesigning macOS app (${identity})..."
    codesign --force --deep --sign "$identity" --timestamp=none "$app_path"
    codesign --verify --deep --strict --verbose=2 "$app_path"
  else
    echo "[BlindRSS Build] Skipping macOS codesign (BLINDRSS_SKIP_MACOS_CODESIGN=1)."
  fi
  echo "[BlindRSS Build] Creating macOS zip..."
  /usr/bin/ditto -c -k --sequesterRsrc --keepParent "$app_path" "$zip_path"
}

if [[ "$MODE" == "dry-run" ]]; then
  detect_python
  echo "[Dry Run] Platform: macos ($UNAME_M)"
  echo "[Dry Run] Python: $PYTHON_EXE"
  echo "[Dry Run] Would prepare .venv, install dependencies, bundle yt-dlp, deno, ffmpeg, and macOS VLC assets."
  echo "[Dry Run] Would ad-hoc sign dist/BlindRSS.app and zip it to dist/BlindRSS-macos-v<version>.zip"
  echo "[Dry Run] ./build.sh release <tag> would dispatch the macOS GitHub Actions build to upload a ZIP to an existing GitHub release."
  exit 0
fi

if [[ "$MODE" == "release" ]]; then
  dispatch_macos_release_workflow "$RELEASE_TAG"
  exit 0
fi

setup_venv
ensure_yt_dlp
ensure_deno
ensure_ffmpeg
ensure_vlc_macos

build_pyinstaller
package_macos

echo "[BlindRSS Build] Done."
