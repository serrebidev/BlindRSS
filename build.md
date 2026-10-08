# BlindRSS Build and Release

This is the only approved workflow for packaging and publishing BlindRSS.

## Every Release, Bluntly

Run `.\build.bat release` on the Windows development machine. This is the one
canonical release command. It bumps the version, tags, creates a draft GitHub
release, builds Linux inside an Ubuntu 22.04 Docker container reached via
`ssh root@serrebiradio.com`, copies the self-contained Linux tarball back and
uploads it with its manifest, then dispatches GitHub Actions, which builds macOS
and builds and signs Windows through SignPath, and publishes the release as
Latest once every asset is uploaded. `build.bat` waits for that run.

You must approve two signing requests in SignPath during every release:
`BlindRSS.exe` first, then the installer. The run waits up to two hours for each.

`./build.sh release` without a tag is rejected. Only run
`./build.sh release vX.Y.Z` to re-dispatch the macOS CI asset for an existing
release.

## Supported Flow Matrix

- Official release from Windows:
  - Run `.\build.bat release`.
  - Windows builds on a GitHub-hosted runner and is signed by SignPath
    (see "Windows Code Signing"). Nothing is signed on this machine.
  - Linux builds on the user-controlled `root@serrebiradio.com` Docker host and
    is copied back, hashed, manifested, and uploaded by `build.bat`.
  - GitHub Actions builds and uploads Windows and macOS, then publishes.
- Local build from macOS or Linux:
  - Run `./build.sh build`.
  - This builds the mac app (macOS) or Linux tarball locally only.
  - If you push to `main`, GitHub Actions will build validation artifacts for macOS and Linux automatically.
- Re-dispatch an existing release:
  - Run `./build.sh release vX.Y.Z` with an existing tag to re-trigger only the
    macOS CI build for a release that's already been created.

## Commands

- Iterative local build: `.\build.bat build`
- Official Windows release build: `.\build.bat release`
- No-change preview: `.\build.bat dry-run`
- Local macOS/Linux package build: `./build.sh build`
- Re-dispatch macOS for an existing release: `./build.sh release vX.Y.Z`
- Local macOS/Linux preview: `./build.sh dry-run`

## Mandatory Release Rule

Use `.\build.bat release` on Windows to cut a release—never hand-assemble a GitHub release. It:

- Bumps `core/version.py`, tags Git, pushes, and creates the GitHub release as a draft.
- Builds Linux over SSH on `root@serrebiradio.com`, verifies the tarball includes
  the executable and bundled Python runtime, uploads it and
  `BlindRSS-update-linux.json`, then dispatches GitHub Actions with Linux
  disabled so CI builds Windows and macOS.
- The `windows` CI job builds the app, has SignPath sign `BlindRSS.exe`, builds
  the ZIP and the Program Files installer around the signed exe, has SignPath
  sign the installer, verifies all three signatures, and writes
  `BlindRSS-update.json` with both SHA-256 hashes and the signing thumbprint.
- Pushes to `main` also trigger GitHub Actions workflow builds for macOS and Linux as workflow artifacts so you can validate packaging without publishing a release. The Windows CI job only runs on `workflow_dispatch` (release cuts), not on every push, since it's a heavier build.
- The release stays a draft until the workflow's `publish` job has seen all seven assets; it then publishes it as Latest. `build.bat release` waits for the run, then verifies there are no draft releases and that GitHub's `/releases/latest` endpoint points at the new tag before exiting. If the run fails, the draft stays: fix the cause and `gh run rerun <id> --failed`. Never leave draft releases behind. Do not automatically delete releases during this check; publish or delete drafts manually by exact tag if needed.

## Updater Visibility Rule

BlindRSS auto-update does not look at Git tags, commits on `main`, or GitHub Actions artifacts. It checks GitHub's `repos/serrebidev/BlindRSS/releases/latest` endpoint, downloads its platform manifest from that release, and then downloads the asset named by that manifest:

- Windows portable/legacy: `BlindRSS-update.json` -> `BlindRSS-vX.Y.Z.zip`
- Windows installed: `BlindRSS-update.json` -> `BlindRSS-Setup-vX.Y.Z.exe` (the
  manifest keeps the ZIP as its canonical asset and adds signed-installer
  metadata for installer-managed copies)
- macOS: `BlindRSS-update-macos.json` -> `BlindRSS-macos-vX.Y.Z.zip`
- Linux: `BlindRSS-update-linux.json` -> `BlindRSS-linux-vX.Y.Z.tar.gz`

`build.bat release` creates the Linux manifest after copying the server-built
artifact back to Windows. The dispatched workflow creates the Windows and macOS
manifests and assets. Nothing is visible to the updater until the workflow
publishes the draft.

After cutting a release, the latest endpoint must return the new tag:

```powershell
gh api repos/serrebidev/BlindRSS/releases/latest --jq .tag_name
```

If this returns the previous tag, users will see "BlindRSS is up to date" for that previous version even when newer code exists on `main`.

`./build.sh release vX.Y.Z` re-dispatches the macOS CI build for an existing
release. It does not bump the version or create a new release.

## Windows Code Signing (SignPath)

Release binaries are signed with a certificate issued to SignPath Foundation.
The private key never leaves SignPath's HSM, and SignPath only signs artifacts
that GitHub proves were built from this repository on a GitHub-hosted runner.
That is why Windows cannot be built or signed locally for a release.

- SignPath project `BlindRSS`, artifact configuration `exe-in-zip` (takes a `version` parameter): a ZIP holding
  one `BlindRSS*.exe` whose version resource has product name `BlindRSS` and
  product version equal to the release version.
- Signing policy `release-signing`: the trusted certificate; every request needs
  approval in SignPath. Used by real releases only.
- Signing policy `test-signing`: an untrusted test certificate, no approval.
  Used by `cloud-release.yml` dry runs.
- Repo secret `SIGNPATH_API_TOKEN`: API token of the SignPath CI user, which is
  a submitter on both policies. Set it with
  `gh secret set SIGNPATH_API_TOKEN --repo serrebidev/BlindRSS` (reads stdin).
- The organization ID, project slug and artifact configuration slug are not
  secret and are set in `env:` at the top of `cross-platform-release.yml`.

Test the whole pipeline without publishing or spending a release signature
(builds `main` as it is, signs with `test-signing`, uploads workflow artifacts only):

```powershell
gh workflow run cloud-release.yml -f dry_run=true
```

The Linux CI job remains enabled on ordinary pushes as packaging validation and
can be manually selected for an existing release, but it is not part of the
default release dispatch.

## Windows Release Prerequisites

- Windows with Python 3.14 preferred (`python` or `py` on PATH).
- VLC 64-bit installed (expected at `C:\Program Files\VideoLAN\VLC`).
- GitHub CLI (`gh`) authenticated for `release` mode.
- Windows SDK `signtool.exe` for signed builds/releases.
- Inno Setup 6 or 7. `build.bat` auto-detects per-user installs at
  `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`, standard Program Files
  installs, and `ISCC.exe` on PATH. Set `INNO_SETUP_COMPILER` to override.
- Network access (the script installs deps and can download `yt-dlp.exe` and `deno.exe`).
- OpenSSH `ssh` and `scp`, with non-interactive key access to
  `root@serrebiradio.com`.

## Remote Linux Release Prerequisites

- `root@serrebiradio.com` must be reachable with key-based SSH authentication.
- The host needs Git and a running Docker daemon. Its host Python, VLC, ffmpeg,
  and GUI packages are irrelevant because the tracked Ubuntu 22.04 container
  provisions Python 3.12 with `uv`, compiles current wxPython with GTK/WebKit development dependencies,
  and supplies the remaining build/runtime dependencies.
- `tools/build_linux_docker.sh` builds the current checkout, verifies the
  tarball contains `BlindRSS/BlindRSS` and a bundled `libpython`, and leaves the
  artifact in `dist/` for `build.bat` to copy.
- `build.bat` clones the exact release tag into a `mktemp` directory under
  `/tmp`, builds there, copies the artifact to Windows, and removes only that
  resolved temporary directory.

## macOS Local Build Prerequisites

- Python 3.14 preferred (`python3` preferred).
- `curl` and `unzip`.
- Deno is bundled by `build.sh`.
- `yt-dlp` is bundled by `build.sh`.
- `ffmpeg` available on PATH.
- macOS: VLC installed at `/Applications/VLC.app`, set `BLINDRSS_VLC_APP`, or let `build.sh` download the pinned VLC DMG into `.build/vlc`.
- macOS: the generated `.app` is ad-hoc signed by default with the free local `codesign` identity (`-`). This is not notarization.

## Linux Local Build Prerequisites

- Python 3.14 preferred (`python3` preferred).
- `curl`, `unzip`, and `tar`.
- Deno and `yt-dlp` are bundled by `build.sh`.
- `ffmpeg` available on PATH.
- System VLC installed (e.g. `sudo apt-get install vlc libvlc-dev`) so `libvlc.so*` and the VLC plugins directory are present. Override with `BLINDRSS_VLC_LIB_DIR` / `BLINDRSS_VLC_PLUGINS` if installed in a non-standard location.
- wxPython: pip cannot find a universal Linux wheel, so either install build deps for a source build or point pip at the prebuilt GTK3 wheel index matching your distro, e.g.:

  ```bash
  export PIP_FIND_LINKS="https://extras.wxpython.org/wxPython4/extras/linux/gtk3/ubuntu-22.04"
  ./build.sh build
  ```

- Output is a `dist/BlindRSS-linux-vX.Y.Z.tar.gz`; there is no code signing on Linux.

## What Each Mode Does

### `build`

- Sets up/uses `.venv`.
- Installs dependencies.
- Runs PyInstaller using `main.spec`.
- Verifies the built exe's VERSIONINFO resource (`tools\verify_version_resource.py`)
  and fails the build if it is missing or does not match `core\version.py`. This is
  what NVDA's app-version command and the JAWS equivalent read; an unstamped exe
  makes them announce "Application unknown, version not detected".
- Preserves `dist\BlindRSS` user data (`rss.db`, `rss.db-wal`, `rss.db-shm`, `podcasts\`) between iterative builds.
- Signs with whatever local certificate `signtool /a` finds, when possible (or
  skip with `SKIP_SIGN=1`). That is a development signature only; it is not the
  release certificate and is never published.
- Produces:
  - `dist\BlindRSS\`
  - `dist\BlindRSS-vX.Y.Z.zip`
  - `dist\BlindRSS-Setup-vX.Y.Z.exe`
  - `BlindRSS.exe` in repo root
  - `BlindRSS.zip` in repo root

### `release`

- Computes next version and bumps `core/version.py`.
- Does not build Windows. Produces `dist\release-notes-vX.Y.Z.md` and the Linux
  tarball and manifest.
- Updates `CHANGELOG.md`, commits the version bump + changelog entry, tags,
  pushes, creates a draft GitHub release, builds/uploads Linux through
  `root@serrebiradio.com`, then dispatches the `cross-platform-release.yml`
  workflow to build and attach Windows and macOS, waits for it, and verifies the
  release is published as Latest.

### `app` and `package`

The two halves of `build`, used by the `windows` CI job so SignPath can sign
`BlindRSS.exe` in between. `app` runs PyInstaller only. `package` builds the ZIP
and the installer from the existing `dist\BlindRSS`. Neither signs.

## Windows Installer and Data Locations

- The installer is per-machine and requires elevation (`PrivilegesRequired=admin`).
  It installs the program into Program Files (`{autopf}\BlindRSS`): `C:\Program
  Files\BlindRSS` for the x64 build, `C:\Program Files (x86)\BlindRSS` for an x86
  build (`{autopf}` + `ArchitecturesInstallIn64BitMode=x64compatible`).
- It creates all-users Start Menu/uninstall registration and an optional desktop
  shortcut.
- Installer-managed copies carry `.windows-installed` beside `BlindRSS.exe`.
  That marker makes packaged Windows BlindRSS keep all mutable state outside the
  read-only install directory: `%APPDATA%\BlindRSS` for `config.json`, `rss.db`,
  logs, imported cookies, and playback cache; `%LOCALAPPDATA%\BlindRSS\bin` for
  the runtime-managed/self-updating `yt-dlp.exe`; and the user's **Downloads**
  folder (`Downloads\BlindRSS`) for episode downloads. Any of these can be
  overridden in Settings.
- On first installed launch, legacy app-folder config/database/download data is
  copied into `%APPDATA%\BlindRSS`. Existing roaming files win, SQLite migration
  uses the backup API (including committed WAL data), and legacy originals are
  retained for rollback.
- The portable ZIP has no installed marker and retains app-folder storage.
- Uninstall removes the application but intentionally leaves
  `%APPDATA%\BlindRSS` intact.
- Installed copies use the signed installer for in-app updates. Because the
  install lives in Program Files, the update runs the signed setup elevated, so
  Windows shows a single UAC consent prompt per update. Portable and older copies
  continue using the ZIP updater (no elevation).

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
  - Installs Python dependencies (wxPython needs a prebuilt GTK3 wheel; see prerequisites).
  - Bundles `yt-dlp`, `deno`, `ffmpeg`, and system VLC `libvlc.so*` + plugins.
  - Runs PyInstaller via `portable.spec`.
  - Produces:
    - `dist/BlindRSS/`
    - `dist/BlindRSS-linux-vX.Y.Z.tar.gz`

### `build.sh release`

- **No tag given** (`./build.sh release`): rejected with instructions to run the
  canonical Windows `.\build.bat release` process.
- **Tag given** (`./build.sh release vX.Y.Z`): requires that tag's GitHub
  release to already exist and dispatches `cross-platform-release.yml` with
  Windows and Linux disabled, rebuilding macOS only. It does not bump versions
  or create a new release.

## Optional Environment Variables

- `SIGNTOOL_PATH`: override default signtool path (local `build` only).
- `INNO_SETUP_COMPILER`: full path to `ISCC.exe` when auto-detection is not
  sufficient.
- `SKIP_SIGN=1`: skip signing in `build` mode only.
- `BLINDRSS_VLC_APP`: override the macOS VLC app bundle path for `build.sh`.
- `BLINDRSS_VLC_VERSION`: override the VLC version downloaded by `build.sh` when no macOS VLC app bundle is found. Default is `3.0.23`.
- `BLINDRSS_VLC_SHA256`: override the expected SHA-256 for a custom macOS VLC DMG download.
- `BLINDRSS_CODESIGN_IDENTITY`: override the macOS `codesign` identity used by `build.sh`. Default is `-` (ad-hoc signing).
- `BLINDRSS_SKIP_MACOS_CODESIGN=1`: skip ad-hoc signing in `build.sh`.
- `BLINDRSS_VLC_LIB_DIR`: override the directory `build.sh`/`portable.spec` search for `libvlc.so*` on Linux.
- `BLINDRSS_VLC_PLUGINS`: override the VLC plugins directory bundled on Linux.
- `LINUX_BUILD_HOST`: SSH destination for release Linux builds. Default:
  `root@serrebiradio.com`.
- `LINUX_BUILD_REPO_URL`: Git URL cloned by the remote release builder. Default:
  `https://github.com/serrebidev/BlindRSS.git`.
- `BLINDRSS_LINUX_BUILD_IMAGE`: Docker image tag used/cached by
  `tools/build_linux_docker.sh`. Default:
  `blindrss-linux-builder:ubuntu-22.04`.

## Typical Usage

```powershell
.\build.bat build
```

```bash
./build.sh build
```

See `README.md` for end-user usage and feature overview.
