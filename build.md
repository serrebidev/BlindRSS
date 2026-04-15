# BlindRSS Build and Release

This is the only approved workflow for packaging and publishing BlindRSS.

## Commands

- Iterative local build: `.\build.bat build`
- Official release: `.\build.bat release`
- No-change preview: `.\build.bat dry-run`
- Local macOS/Linux package build: `./build.sh build`
- Local macOS/Linux preview: `./build.sh dry-run`

## Mandatory Release Rule

Always publish with `.\build.bat release`.

Do not publish manually from GitHub UI/CLI without running this script first. The script is required because it:

- Creates `BlindRSS-update.json` for auto-updates.
- Computes the release ZIP SHA-256 hash.
- Signs `BlindRSS.exe` when `signtool.exe` is available.
- Bumps `core/version.py`, tags Git, pushes, and creates the GitHub release.
- Dispatches GitHub Actions builds for macOS and Linux/AppImage release assets after the Windows release is created.
- Pushes to `main` also trigger GitHub Actions workflow builds for Windows, macOS, and Linux as workflow artifacts so you can validate cross-platform packaging from macOS without publishing a release.

## Windows Release Prerequisites

- Windows with Python 3.12+ (`python` or `py` on PATH).
- VLC 64-bit installed (expected at `C:\Program Files\VideoLAN\VLC`).
- GitHub CLI (`gh`) authenticated for `release` mode.
- Windows SDK `signtool.exe` for signed builds/releases.
- Network access (the script installs deps and can download `yt-dlp.exe` and `deno.exe`).

## macOS/Linux Local Build Prerequisites

- Python 3.12+ (`python3` preferred).
- `curl` and `unzip`.
- Deno is bundled by `build.sh`.
- `yt-dlp` is bundled by `build.sh`.
- `ffmpeg` available on PATH.
- macOS: VLC installed at `/Applications/VLC.app`, or set `BLINDRSS_VLC_APP`.
- macOS: the generated `.app` is ad-hoc signed by default with the free local `codesign` identity (`-`). This is not notarization.
- Linux: VLC/libvlc installed so the script can bundle `libvlc` and the VLC plugins directory.
- Linux AppImage packaging: `build.sh` downloads `appimagetool` automatically.

## What Each Mode Does

### `build`

- Sets up/uses `.venv`.
- Installs dependencies.
- Runs PyInstaller using `main.spec`.
- Preserves `dist\BlindRSS` user data (`rss.db`, `rss.db-wal`, `rss.db-shm`, `podcasts\`) between iterative builds.
- Signs when possible (or skip with `SKIP_SIGN=1`).
- Produces:
  - `dist\BlindRSS\`
  - `dist\BlindRSS-vX.Y.Z.zip`
  - `BlindRSS.exe` in repo root
  - `BlindRSS.zip` in repo root

### `release`

- Computes next version and bumps `core/version.py`.
- Performs a clean build (wipes `build\` and `dist\`).
- Signs executable.
- Produces:
  - `dist\BlindRSS-vX.Y.Z.zip`
  - `dist\BlindRSS-update.json`
  - `dist\release-notes-vX.Y.Z.md`
- Commits version bump, tags, pushes, creates GitHub release assets (ZIP + manifest), and dispatches the `cross-platform-release.yml` GitHub Actions workflow to attach macOS and Linux/AppImage assets to the same release.

### `dry-run`

- Shows next version and planned release steps.
- Does not modify files or Git state.

### `build.sh build`

- On macOS:
  - Creates/uses `.venv`.
  - Installs Python dependencies.
  - Bundles `yt-dlp`, `deno`, `ffmpeg`, and VLC runtime files.
  - Runs PyInstaller via `portable.spec`.
  - Ad-hoc signs `dist/BlindRSS.app` unless disabled.
  - Produces:
    - `dist/BlindRSS.app`
    - `dist/BlindRSS-macos-vX.Y.Z.zip`

- On Linux:
  - Creates/uses `.venv`.
  - Installs Python dependencies.
  - Bundles `yt-dlp`, `deno`, `ffmpeg`, and VLC runtime files.
  - Runs PyInstaller via `portable.spec`.
  - Stages an AppDir and creates:
    - `dist/BlindRSS/`
    - `dist/BlindRSS-linux-<arch>-vX.Y.Z.AppImage`

### `build.sh release`

- Intentionally rejected.
- Official releases still go through `.\build.bat release` so the Windows updater manifest and GitHub release flow stay authoritative.

## Optional Environment Variables

- `SIGNTOOL_PATH`: override default signtool path.
- `SIGN_CERT_THUMBPRINT`: force manifest signing thumbprint value.
- `SKIP_SIGN=1`: skip signing in `build` mode only.
- `BLINDRSS_VLC_APP`: override the macOS VLC app bundle path for `build.sh`.
- `BLINDRSS_CODESIGN_IDENTITY`: override the macOS `codesign` identity used by `build.sh`. Default is `-` (ad-hoc signing).
- `BLINDRSS_SKIP_MACOS_CODESIGN=1`: skip ad-hoc signing in `build.sh`.
- `BLINDRSS_VLC_LIB_DIR`: override the Linux libvlc directory for `build.sh`.
- `BLINDRSS_VLC_PLUGINS`: override the Linux VLC plugins directory for `build.sh`.

## Typical Usage

```powershell
.\build.bat build
```

```bash
./build.sh build
```

See `README.md` for end-user usage and feature overview.
