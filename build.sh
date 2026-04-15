#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-build}"
case "$MODE" in
  build|dry-run|release) ;;
  *)
    echo "Usage: ./build.sh <build|dry-run|release>"
    exit 1
    ;;
esac

UNAME_S="$(uname -s)"
UNAME_M="$(uname -m)"

case "$UNAME_S" in
  Darwin)
    PLATFORM="macos"
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
  Linux)
    PLATFORM="linux"
    YTDLP_URL="https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux"
    case "$UNAME_M" in
      x86_64) DENO_ASSET="deno-x86_64-unknown-linux-gnu.zip"; APPIMAGE_ASSET="appimagetool-x86_64.AppImage" ;;
      aarch64|arm64) DENO_ASSET="deno-aarch64-unknown-linux-gnu.zip"; APPIMAGE_ASSET="appimagetool-aarch64.AppImage" ;;
      *)
        echo "[X] Unsupported Linux architecture: $UNAME_M"
        exit 1
        ;;
    esac
    ;;
  *)
    echo "[X] Unsupported platform: $UNAME_S"
    exit 1
    ;;
esac

if [[ "$MODE" == "release" ]]; then
  echo "[X] Official releases must still use .\\build.bat release on Windows."
  echo "[X] ./build.sh is for local macOS/Linux packaging and for GitHub runner builds."
  exit 1
fi

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
  ffmpeg_path="$(command -v ffmpeg || true)"
  if [[ -z "$ffmpeg_path" && "$PLATFORM" == "macos" && -x "$(command -v brew || true)" ]]; then
    echo "[BlindRSS Build] ffmpeg missing. Installing with Homebrew..."
    brew install ffmpeg
    ffmpeg_path="$(command -v ffmpeg || true)"
  fi
  if [[ -z "$ffmpeg_path" ]]; then
    echo "[X] ffmpeg not found on PATH."
    exit 1
  fi
  cp "$ffmpeg_path" "$SCRIPT_DIR/bin/ffmpeg"
  chmod +x "$SCRIPT_DIR/bin/ffmpeg"
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

ensure_vlc_linux() {
  local plugin_dir lib_dir
  plugin_dir="${BLINDRSS_VLC_PLUGINS:-}"
  lib_dir="${BLINDRSS_VLC_LIB_DIR:-}"

  if [[ -z "$plugin_dir" ]]; then
    for candidate in \
      /usr/lib/x86_64-linux-gnu/vlc/plugins \
      /usr/lib/aarch64-linux-gnu/vlc/plugins \
      /usr/lib/vlc/plugins
    do
      if [[ -d "$candidate" ]]; then
        plugin_dir="$candidate"
        break
      fi
    done
  fi

  if [[ -z "$lib_dir" ]]; then
    for candidate in \
      /usr/lib/x86_64-linux-gnu \
      /usr/lib/aarch64-linux-gnu \
      /usr/lib64 \
      /usr/lib
    do
      if compgen -G "$candidate/libvlc.so*" >/dev/null; then
        lib_dir="$candidate"
        break
      fi
    done
  fi

  if [[ -z "$plugin_dir" || -z "$lib_dir" ]]; then
    echo "[X] Linux VLC runtime files were not found."
    echo "[X] Install VLC/libvlc and/or set BLINDRSS_VLC_PLUGINS and BLINDRSS_VLC_LIB_DIR."
    exit 1
  fi

  export BLINDRSS_VLC_PLUGINS="$plugin_dir"
  export BLINDRSS_VLC_LIB_DIR="$lib_dir"
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

ensure_appimagetool() {
  ensure_bin_dir
  APPIMAGETOOL_PATH="$SCRIPT_DIR/bin/appimagetool.AppImage"
  echo "[BlindRSS Build] Ensuring appimagetool is present..."
  download_file "https://github.com/AppImage/appimagetool/releases/download/continuous/$APPIMAGE_ASSET" "$APPIMAGETOOL_PATH"
  chmod +x "$APPIMAGETOOL_PATH"
}

package_linux_appimage() {
  ensure_appimagetool
  local appdir out desktop_path root_desktop root_icon
  appdir="$SCRIPT_DIR/dist/AppDir"
  out="$SCRIPT_DIR/dist/BlindRSS-linux-${UNAME_M}-v${VERSION_NO_V}.AppImage"
  desktop_path="$appdir/usr/share/applications/BlindRSS.desktop"
  root_desktop="$appdir/BlindRSS.desktop"
  root_icon="$appdir/BlindRSS.svg"

  rm -rf "$appdir"
  mkdir -p \
    "$appdir/usr/opt" \
    "$appdir/usr/share/applications" \
    "$appdir/usr/share/icons/hicolor/scalable/apps"

  cp -a "$SCRIPT_DIR/dist/BlindRSS" "$appdir/usr/opt/BlindRSS"

  cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
APP_ROOT="$HERE/usr/opt/BlindRSS"
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
EOF
  chmod +x "$appdir/AppRun"

  cat > "$desktop_path" <<'EOF'
[Desktop Entry]
Type=Application
Name=BlindRSS
Comment=BlindRSS feed reader and audio player
Exec=BlindRSS
Icon=BlindRSS
Terminal=false
Categories=AudioVideo;News;
EOF
  cp "$desktop_path" "$root_desktop"

  cp "$SCRIPT_DIR/assets/blindrss.svg" "$appdir/usr/share/icons/hicolor/scalable/apps/BlindRSS.svg"
  cp "$SCRIPT_DIR/assets/blindrss.svg" "$root_icon"

  echo "[BlindRSS Build] Creating AppImage..."
  APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL_PATH" "$appdir" "$out"
}

if [[ "$MODE" == "dry-run" ]]; then
  detect_python
  echo "[Dry Run] Platform: $PLATFORM ($UNAME_M)"
  echo "[Dry Run] Python: $PYTHON_EXE"
  echo "[Dry Run] Would prepare .venv, install dependencies, bundle yt-dlp, deno, ffmpeg, and platform VLC assets."
  if [[ "$PLATFORM" == "macos" ]]; then
    echo "[Dry Run] Would ad-hoc sign dist/BlindRSS.app and zip it to dist/BlindRSS-macos-v<version>.zip"
  else
    echo "[Dry Run] Would build dist/BlindRSS, stage an AppDir, and create dist/BlindRSS-linux-${UNAME_M}-v<version>.AppImage"
  fi
  exit 0
fi

setup_venv
ensure_yt_dlp
ensure_deno
ensure_ffmpeg

if [[ "$PLATFORM" == "macos" ]]; then
  ensure_vlc_macos
else
  ensure_vlc_linux
fi

build_pyinstaller

if [[ "$PLATFORM" == "macos" ]]; then
  package_macos
else
  package_linux_appimage
fi

echo "[BlindRSS Build] Done."
