# BlindRSS Build and Release

This is the only approved workflow for packaging and publishing BlindRSS.

## Every Release, Bluntly

There are two equivalent ways to cut a release:

- On Windows: run `.\build.bat release`. It bumps the version, builds and signs
  the Windows release locally, creates the GitHub release with the Windows
  assets attached, and dispatches GitHub Actions to build macOS and Linux.
- On macOS/Linux: run `./build.sh release` (no tag). It bumps the version,
  creates the GitHub release with no assets yet, and dispatches GitHub Actions
  to build **all three platforms** — including a signed Windows build, using a
  code-signing certificate stored as the `WINDOWS_CODESIGN_PFX` /
  `WINDOWS_CODESIGN_PASSWORD` repo secrets.

Only run `./build.sh release vX.Y.Z` (with an existing tag) if you need to
manually rerun or republish CI-built assets for a release that's already been
created.

You do not normally need to build locally on both Windows and macOS — pick
whichever machine you're on and run its release command.

## Supported Flow Matrix

- Official release from Windows:
  - Run `.\build.bat release`.
  - Windows builds locally.
  - GitHub Actions builds macOS and Linux automatically and uploads the mac ZIP and Linux tarball to the same GitHub release.
- Local build from macOS or Linux:
  - Run `./build.sh build`.
  - This builds the mac app (macOS) or Linux tarball locally only.
  - If you push to `main`, GitHub Actions will build validation artifacts for macOS and Linux automatically.
- Official release from macOS:
  - Run `./build.sh release` (no tag) on macOS or Linux.
  - This bumps `core/version.py`, tags, pushes, and creates the GitHub release (no assets yet).
  - It then dispatches `cross-platform-release.yml`, which builds and attaches
    the signed **Windows** installer/ZIP/`BlindRSS-update.json` (via a
    `windows-latest` runner using the `WINDOWS_CODESIGN_PFX` /
    `WINDOWS_CODESIGN_PASSWORD` secrets), plus the **macOS** and **Linux**
    assets, all to that same release.
  - Requires `WINDOWS_CODESIGN_PFX` and `WINDOWS_CODESIGN_PASSWORD` to be set
    as repo secrets (see "GitHub Actions Windows Build" below).
- Re-dispatch an existing release:
  - Run `./build.sh release vX.Y.Z` with an existing tag to re-trigger the
    Windows/macOS/Linux CI build for a release that's already been created
    (Windows only runs there too — no more mac/Linux-only re-dispatch).
  - Windows can still be built and signed locally instead with `.\build.bat release` on a Windows machine.

## Commands

- Iterative local build: `.\build.bat build`
- Official Windows release build: `.\build.bat release`
- No-change preview: `.\build.bat dry-run`
- Local macOS/Linux package build: `./build.sh build`
- Official macOS/Linux/Windows release build: `./build.sh release`
- Re-dispatch CI build for an existing release: `./build.sh release vX.Y.Z`
- Local macOS/Linux preview: `./build.sh dry-run`

## Mandatory Release Rule

Use `.\build.bat release` (Windows) or `./build.sh release` (macOS/Linux) to cut a release — never hand-assemble a GitHub release. Whichever one you run:

- Creates `BlindRSS-update.json` for Windows auto-updates (locally by `build.bat`, or by the `windows` CI job when dispatched from `build.sh`).
- Computes the release ZIP SHA-256 hash.
- Builds the Program Files Windows installer and computes its SHA-256 hash.
- Signs `BlindRSS.exe` and the installer — locally via `signtool.exe` for `build.bat`, or in CI via the `WINDOWS_CODESIGN_PFX`/`WINDOWS_CODESIGN_PASSWORD` secrets for `build.sh`.
- Bumps `core/version.py`, tags Git, pushes, and creates the GitHub release.
- Dispatches the GitHub Actions release-asset build. `build.bat` passes
  `build_windows=false` so CI builds only macOS/Linux after Windows was built
  and signed locally; `build.sh` keeps the default and dispatches all three.
- Pushes to `main` also trigger GitHub Actions workflow builds for macOS and Linux as workflow artifacts so you can validate packaging without publishing a release. The Windows CI job only runs on `workflow_dispatch` (release cuts), not on every push, since it's a heavier build.
- `build.bat release` forces the created GitHub release to published/latest, verifies there are no draft releases, and verifies GitHub's `/releases/latest` endpoint points at the new tag before exiting. Never leave draft releases behind. Do not automatically delete releases during this check; publish or delete drafts manually by exact tag if needed.

## Updater Visibility Rule

BlindRSS auto-update does not look at Git tags, commits on `main`, or GitHub Actions artifacts. It checks GitHub's `repos/serrebidev/BlindRSS/releases/latest` endpoint, downloads its platform manifest from that release, and then downloads the asset named by that manifest:

- Windows portable/legacy: `BlindRSS-update.json` -> `BlindRSS-vX.Y.Z.zip`
- Windows installed: `BlindRSS-update.json` -> `BlindRSS-Setup-vX.Y.Z.exe` (the
  manifest keeps the ZIP as its canonical asset and adds signed-installer
  metadata for installer-managed copies)
- macOS: `BlindRSS-update-macos.json` -> `BlindRSS-macos-vX.Y.Z.zip`
- Linux: `BlindRSS-update-linux.json` -> `BlindRSS-linux-vX.Y.Z.tar.gz`

When `.\build.bat release` runs on Windows, the Windows manifest is created locally. When `./build.sh release` runs on macOS/Linux, the Windows manifest instead comes from the `windows` job in `cross-platform-release.yml` (built and signed on a `windows-latest` runner). Either way, the macOS and Linux manifests are always created and uploaded by the dispatched `cross-platform-release.yml` job (alongside their assets), so all platform manifests appear on the release a few minutes after the release is created, not instantly. Until each job finishes, that platform's clients report "manifest not found" for the new tag.

After cutting a release, the latest endpoint must return the new tag:

```powershell
gh api repos/serrebidev/BlindRSS/releases/latest --jq .tag_name
```

If this returns the previous tag, users will see "BlindRSS is up to date" for that previous version even when newer code exists on `main`.

`./build.sh release vX.Y.Z` (with an existing tag) re-dispatches the Windows/macOS/Linux CI build for a release that's already been created — useful to retry a failed CI job or republish an asset. It does not bump the version or create a new release.

## GitHub Actions Windows Build

`cross-platform-release.yml`'s `windows` job lets a release be cut entirely from macOS/Linux without touching a Windows machine. It only runs on `workflow_dispatch` (an actual release cut), reuses `build.bat build` unchanged, and needs two repo secrets:

- `WINDOWS_CODESIGN_PFX`: base64-encoded, password-protected PFX export of the code-signing certificate (`Export-PfxCertificate` on the machine that holds it, then base64-encode the file).
- `WINDOWS_CODESIGN_PASSWORD`: the PFX's password.

The job imports the cert into `Cert:\CurrentUser\My` on the runner, installs VLC and Inno Setup via Chocolatey (VLC must land at `C:\Program Files\VideoLAN\VLC` — the path `main.spec` hardcodes), locates `signtool.exe` under the Windows SDK, then runs `build.bat build` with `SIGNTOOL_PATH` pointed at it. Rotate these secrets with `gh secret set WINDOWS_CODESIGN_PFX --repo serrebidev/BlindRSS` / `gh secret set WINDOWS_CODESIGN_PASSWORD --repo serrebidev/BlindRSS` (each reads the value from stdin) if the certificate is ever replaced.

An earlier attempt at a Windows CI job was reverted because the runner had no VLC installed at the path `main.spec` expects, so `libvlc.dll` was missing and the PyInstaller build failed. This version fixes that by installing VLC via Chocolatey before building.

## Windows Release Prerequisites

- Windows with Python 3.14 preferred (`python` or `py` on PATH).
- VLC 64-bit installed (expected at `C:\Program Files\VideoLAN\VLC`).
- GitHub CLI (`gh`) authenticated for `release` mode.
- Windows SDK `signtool.exe` for signed builds/releases.
- Inno Setup 6 or 7. `build.bat` auto-detects per-user installs at
  `%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe`, standard Program Files
  installs, and `ISCC.exe` on PATH. Set `INNO_SETUP_COMPILER` to override.
- Network access (the script installs deps and can download `yt-dlp.exe` and `deno.exe`).
- These prerequisites apply to the machine actually building Windows — either your local Windows machine (`build.bat`) or the GitHub Actions `windows-latest` runner (`build.sh release`, see "GitHub Actions Windows Build" above), which provisions VLC and Inno Setup itself.

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
- Signs when possible (or skip with `SKIP_SIGN=1`).
- Produces:
  - `dist\BlindRSS\`
  - `dist\BlindRSS-vX.Y.Z.zip`
  - `dist\BlindRSS-Setup-vX.Y.Z.exe`
  - `BlindRSS.exe` in repo root
  - `BlindRSS.zip` in repo root

### `release`

- Computes next version and bumps `core/version.py`.
- Performs a clean build (wipes `build\` and `dist\`).
- Compiles gettext `locale\<lang>\LC_MESSAGES\blindrss.po` catalogs to
  generated `.mo` files before PyInstaller runs.
- Signs executable.
- Produces:
  - `dist\BlindRSS-vX.Y.Z.zip`
  - `dist\BlindRSS-Setup-vX.Y.Z.exe`
  - `dist\BlindRSS-update.json`
  - `dist\release-notes-vX.Y.Z.md`
- Updates `CHANGELOG.md`, commits the version bump + changelog entry, tags,
  pushes, creates GitHub release assets (ZIP + installer + manifest), and
  dispatches the `cross-platform-release.yml` GitHub Actions workflow to attach
  the macOS/Linux assets to the same release.

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

- **No tag given** (`./build.sh release`): computes the next version, bumps
  `core/version.py`, writes release notes, updates `CHANGELOG.md`, commits,
  tags, pushes, and creates the GitHub release (no assets yet) — the macOS/Linux
  equivalent of `build.bat release`'s version-bump step. Then dispatches
  `cross-platform-release.yml` with the new tag.
- **Tag given** (`./build.sh release vX.Y.Z`): requires that tag's GitHub
  release to already exist, and just dispatches `cross-platform-release.yml`
  with `release_tag=<tag>` to re-trigger CI for it. Does not bump versions or
  create a new release.
- Either way, GitHub Actions then builds and uploads (with updater manifests):
  the signed **Windows** installer/ZIP (`windows-latest` runner, using the
  `WINDOWS_CODESIGN_PFX`/`WINDOWS_CODESIGN_PASSWORD` secrets), the **macOS**
  ZIP (macOS runner), and the **Linux** tarball (Ubuntu runner).
- Windows can still be built and signed locally instead via `.\build.bat release`
  on a Windows machine, if you'd rather not depend on the CI signing secrets.

## Optional Environment Variables

- `SIGNTOOL_PATH`: override default signtool path.
- `SIGN_CERT_THUMBPRINT`: force manifest signing thumbprint value.
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

## Typical Usage

```powershell
.\build.bat build
```

```bash
./build.sh build
```

See `README.md` for end-user usage and feature overview.
