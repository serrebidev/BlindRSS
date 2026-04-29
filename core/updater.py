import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
import hashlib
from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from packaging.version import Version, InvalidVersion

from core.config import APP_DIR
from core.utils import safe_requests_get
from core.version import APP_VERSION
from core.update_config import (
    EXE_NAME,
    GITHUB_OWNER,
    GITHUB_REPO,
    UPDATE_ASSET_EXTENSION,
    UPDATE_MANIFEST_NAME,
)

log = logging.getLogger(__name__)

_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)(?:\.(\d+))?$")


def _normalize_thumbprint(value: Optional[str]) -> str:
    if not value:
        return ""
    return value.replace(" ", "").strip().upper()


def _normalize_thumbprints(values: Iterable[str]) -> Tuple[str, ...]:
    normalized = {_normalize_thumbprint(value) for value in values if value}
    normalized.discard("")
    return tuple(sorted(normalized))


def _env_thumbprints() -> Tuple[str, ...]:
    raw = os.environ.get("BLINDRSS_TRUSTED_SIGNING_THUMBPRINTS", "")
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _extract_manifest_thumbprints(payload: dict) -> Tuple[str, ...]:
    raw = payload.get("signing_thumbprints") or payload.get("signing_thumbprint")
    if isinstance(raw, str):
        return (raw,)
    if isinstance(raw, list):
        return tuple(str(item).strip() for item in raw if item)
    return ()


@dataclass
class UpdateInfo:
    version: Version
    tag: str
    published_at: str
    notes_summary: str
    asset_name: str
    download_url: str
    sha256: str
    signing_thumbprints: Tuple[str, ...] = ()


@dataclass
class UpdateCheckResult:
    status: str
    message: str
    info: Optional[UpdateInfo] = None


def _parse_version(value: str) -> Optional[Version]:
    if not value:
        return None
    value = str(value).strip()
    m = _SEMVER_RE.match(value)
    if not m:
        return None
    major, minor, patch = m.groups()
    normalized = f"{int(major)}.{int(minor)}.{int(patch or 0)}"
    try:
        return Version(normalized)
    except InvalidVersion:
        return None


def _format_version_tag(version: Version) -> str:
    return f"v{version.major}.{version.minor}.{version.micro}"


def _dedupe_paths(paths: Iterable[str]) -> Tuple[str, ...]:
    seen = set()
    out = []
    for path in paths:
        raw = str(path or "").strip()
        if not raw:
            continue
        key = os.path.normcase(os.path.abspath(raw))
        if key in seen:
            continue
        seen.add(key)
        out.append(raw)
    return tuple(out)


def _powershell_executables() -> Tuple[str, ...]:
    candidates = []
    for name in ("pwsh", "powershell"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidates.extend(
        [
            os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe"),
            os.path.join(system_root, "Sysnative", "WindowsPowerShell", "v1.0", "powershell.exe"),
        ]
    )
    return _dedupe_paths(path for path in candidates if os.path.isfile(path) or shutil.which(path))


def _ps_single_quote(value: str) -> str:
    return "'" + str(value or "").replace("'", "''") + "'"


def _fetch_latest_release() -> Tuple[Optional[dict], Optional[str]]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
    headers = {"Accept": "application/vnd.github+json"}
    try:
        resp = safe_requests_get(url, headers=headers, timeout=15)
    except Exception as e:
        return None, f"Network error while checking GitHub: {e}"

    if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
        reset = resp.headers.get("X-RateLimit-Reset", "")
        msg = "GitHub API rate limit reached. Try again later."
        if reset:
            msg = f"{msg} Reset time (epoch): {reset}"
        return None, msg

    if not resp.ok:
        return None, f"GitHub API error: HTTP {resp.status_code}"

    try:
        return resp.json(), None
    except Exception as e:
        return None, f"Invalid GitHub response: {e}"


def _find_release_asset(release: dict, name: str) -> Optional[dict]:
    assets = release.get("assets") or []
    for asset in assets:
        if asset.get("name") == name:
            return asset
    return None


def _download_json(url: str, timeout: int = 20) -> Tuple[Optional[dict], Optional[str]]:
    try:
        resp = safe_requests_get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json(), None
    except Exception as e:
        return None, f"Failed to download update metadata: {e}"


def check_for_updates() -> UpdateCheckResult:
    current = _parse_version(APP_VERSION)
    if not current:
        return UpdateCheckResult("error", f"Invalid current version: {APP_VERSION}")

    release, err = _fetch_latest_release()
    if err:
        return UpdateCheckResult("error", err)
    if not release:
        return UpdateCheckResult("error", "No release data from GitHub.")

    tag = str(release.get("tag_name") or "").strip()
    latest = _parse_version(tag)
    if not latest:
        return UpdateCheckResult("error", f"Latest release tag is not semver: {tag}")

    if latest <= current:
        return UpdateCheckResult("up_to_date", f"BlindRSS is up to date ({_format_version_tag(current)}).")

    manifest_asset = _find_release_asset(release, UPDATE_MANIFEST_NAME)
    if not manifest_asset:
        return UpdateCheckResult("error", f"Update manifest '{UPDATE_MANIFEST_NAME}' not found in release assets.")

    manifest, err = _download_json(manifest_asset.get("browser_download_url", ""))
    if err:
        return UpdateCheckResult("error", err)
    if not manifest:
        return UpdateCheckResult("error", "Update manifest is empty.")

    manifest_version = _parse_version(str(manifest.get("version") or ""))
    if not manifest_version:
        return UpdateCheckResult("error", "Update manifest has invalid version.")
    if manifest_version != latest:
        return UpdateCheckResult("error", "Update manifest version does not match the latest release.")

    asset_name = manifest.get("asset") or manifest.get("asset_name") or ""
    if not asset_name:
        return UpdateCheckResult("error", "Update manifest is missing asset name.")
    if not asset_name.endswith(UPDATE_ASSET_EXTENSION):
        return UpdateCheckResult("error", f"Update asset must be a {UPDATE_ASSET_EXTENSION} file.")

    asset = _find_release_asset(release, asset_name)
    if not asset:
        return UpdateCheckResult("error", f"Update asset '{asset_name}' not found in release assets.")

    download_url = asset.get("browser_download_url") or manifest.get("download_url") or ""
    if not download_url:
        return UpdateCheckResult("error", "Update manifest is missing a download URL.")

    sha256 = str(manifest.get("sha256") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return UpdateCheckResult("error", "Update manifest has an invalid SHA-256 hash.")

    notes_summary = str(manifest.get("notes_summary") or "").strip()
    published_at = str(release.get("published_at") or manifest.get("published_at") or "")
    manifest_thumbprints = _extract_manifest_thumbprints(manifest)
    allowed_thumbprints = _normalize_thumbprints(list(manifest_thumbprints) + list(_env_thumbprints()))

    info = UpdateInfo(
        version=latest,
        tag=_format_version_tag(latest),
        published_at=published_at,
        notes_summary=notes_summary,
        asset_name=asset_name,
        download_url=download_url,
        sha256=sha256,
        signing_thumbprints=allowed_thumbprints,
    )
    return UpdateCheckResult("update_available", "Update available.", info)


def is_update_supported() -> bool:
    if not getattr(sys, "frozen", False):
        return False
    helper_path = os.path.join(APP_DIR, "update_helper.bat")
    return os.path.isfile(helper_path)


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_zip(zip_path: str, dest_dir: str) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest_dir)


def _find_staging_root(extract_dir: str) -> str:
    entries = [e for e in os.listdir(extract_dir) if e and not e.startswith(".")]
    if len(entries) == 1:
        candidate = os.path.join(extract_dir, entries[0])
        if os.path.isdir(candidate):
            return candidate
    return extract_dir


def _verify_authenticode_signature(exe_path: str, allowed_thumbprints: Iterable[str]) -> Tuple[bool, str]:
    allowed = set(_normalize_thumbprints(allowed_thumbprints))
    ps_script = (
        "$ErrorActionPreference = 'Stop';"
        "Import-Module Microsoft.PowerShell.Security -ErrorAction SilentlyContinue;"
        f"$sig = Get-AuthenticodeSignature -FilePath {_ps_single_quote(exe_path)};"
        "$subject = if ($sig.SignerCertificate) { $sig.SignerCertificate.Subject } else { '' };"
        "$thumb = if ($sig.SignerCertificate) { $sig.SignerCertificate.Thumbprint } else { '' };"
        "$out = @{Status=$sig.Status.ToString(); StatusMessage=$sig.StatusMessage; Subject=$subject; Thumbprint=$thumb};"
        "$out | ConvertTo-Json -Compress"
    )

    last_error = ""
    for powershell_exe in _powershell_executables():
        try:
            proc = subprocess.run(
                [powershell_exe, "-NoProfile", "-Command", ps_script],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as e:
            last_error = f"{powershell_exe}: {e}"
            continue

        if proc.returncode != 0:
            msg = proc.stderr.strip() or proc.stdout.strip() or "Unknown error"
            last_error = f"{powershell_exe}: {msg}"
            continue

        try:
            data = json.loads(proc.stdout.strip())
        except Exception as e:
            last_error = f"{powershell_exe}: invalid Authenticode data: {e}"
            continue

        status = str(data.get("Status") or "").strip()
        status_msg = str(data.get("StatusMessage") or "").strip()
        thumbprint = _normalize_thumbprint(data.get("Thumbprint"))
        if status.lower() != "valid":
            if thumbprint and thumbprint in allowed:
                return True, ""
            message = f"Signature check failed: {status} {status_msg}".strip()
            if thumbprint:
                message = f"{message} (thumbprint {thumbprint})"
            return False, message
        return True, ""

    if last_error:
        return False, f"Authenticode verification failed: {last_error}"
    return False, "Authenticode verification failed: PowerShell was not found."


def _launch_update_helper(
    helper_path: str,
    parent_pid: int,
    install_dir: str,
    staging_root: str,
    temp_root: Optional[str] = None,
    debug_mode: bool = False,
    show_log: bool = False,
) -> Tuple[bool, str]:
    try:
        helper_cwd = None
        try:
            helper_cwd = os.path.dirname(helper_path)
        except Exception:
            helper_cwd = None

        # Never set the working directory to the install folder, otherwise Windows can
        # refuse to move/rename it during the swap (current-directory handle lock).
        if not helper_cwd or not os.path.isdir(helper_cwd):
            helper_cwd = tempfile.gettempdir()

        if not debug_mode:
            # Invisible execution
            creationflags = 0
            startupinfo = None
            breakaway_flag = 0
            if sys.platform == "win32":
                create_no_window = 0x08000000  # CREATE_NO_WINDOW
                create_new_process_group = 0x00000200
                breakaway_flag = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
                creationflags = create_no_window | create_new_process_group | breakaway_flag
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0

            cmd = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/c",
                helper_path,
                str(parent_pid),
                install_dir,
                staging_root,
                EXE_NAME,
            ]
            if temp_root:
                cmd.append(temp_root)
            elif show_log:
                cmd.append("")
            if show_log:
                cmd.append("show")
            try:
                subprocess.Popen(
                    cmd,
                    cwd=helper_cwd,
                    creationflags=creationflags,
                    startupinfo=startupinfo,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True
                )
            except Exception:
                if sys.platform == "win32" and breakaway_flag:
                    retry_flags = creationflags & ~breakaway_flag
                    subprocess.Popen(
                        cmd,
                        cwd=helper_cwd,
                        creationflags=retry_flags,
                        startupinfo=startupinfo,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True
                    )
                else:
                    raise
        else:
            # Visible window for debugging
            cmd = [
                os.environ.get("COMSPEC", "cmd.exe"),
                "/c",
                "start",
                "",
                helper_path,
                str(parent_pid),
                install_dir,
                staging_root,
                EXE_NAME,
            ]
            if temp_root:
                cmd.append(temp_root)
            elif show_log:
                cmd.append("")
            if show_log:
                cmd.append("show")
            subprocess.Popen(cmd, cwd=helper_cwd)
            
        return True, ""
    except Exception as e:
        return False, f"Failed to start update helper: {e}"


def _make_update_temp_root(install_dir: str) -> str:
    """Create a temp working directory for updates.

    Prefer a staging directory on the same drive as the install directory to avoid
    cross-volume moves (which can fail for batch scripts or be very slow).
    """
    install_dir = os.path.abspath(str(install_dir or ""))
    try:
        parent = os.path.dirname(install_dir)
    except Exception:
        parent = ""

    candidates: list[str] = []
    if parent:
        candidates.append(os.path.join(parent, "_BlindRSS_update_tmp"))

    for base in candidates:
        try:
            os.makedirs(base, exist_ok=True)
            # Basic writability probe (some locations exist but are not writable).
            probe = os.path.join(base, f".probe_{os.getpid()}_{int(time.time())}")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("ok")
            os.remove(probe)
            return tempfile.mkdtemp(prefix="BlindRSS_update_", dir=base)
        except Exception:
            continue

    return tempfile.mkdtemp(prefix="BlindRSS_update_")


def _safe_remove_dir(path: str, install_dir: str, reason: str) -> None:
    if not path:
        return
    try:
        full_path = os.path.realpath(path)
    except Exception:
        return
    if not os.path.isdir(full_path):
        return

    try:
        install_path = os.path.realpath(install_dir)
    except Exception:
        install_path = install_dir

    install_norm = os.path.normcase(install_path)
    target_norm = os.path.normcase(full_path)
    if target_norm in (install_norm, os.path.normcase(os.path.dirname(install_path))):
        return
    if target_norm == os.path.normcase(os.path.abspath(os.sep)):
        return

    try:
        shutil.rmtree(full_path)
        log.info("Removed update artifact (%s): %s", reason, full_path)
    except Exception as e:
        log.debug("Failed to remove update artifact (%s): %s", reason, e)


def cleanup_update_artifacts(install_dir: Optional[str] = None) -> None:
    """Remove leftover update folders from previous runs."""
    if not getattr(sys, "frozen", False):
        return

    install_dir = os.path.abspath(install_dir or APP_DIR)
    parent_dir = os.path.dirname(install_dir)
    install_base = os.path.basename(install_dir).lower()

    for path in glob.glob(f"{install_dir}_backup_*"):
        base = os.path.basename(path).lower()
        if base.startswith(f"{install_base}_backup_"):
            _safe_remove_dir(path, install_dir, "backup")

    update_tmp_parent = os.path.join(parent_dir, "_BlindRSS_update_tmp")
    try:
        if os.path.isdir(update_tmp_parent):
            for entry in os.listdir(update_tmp_parent):
                if entry.startswith("BlindRSS_update_"):
                    _safe_remove_dir(os.path.join(update_tmp_parent, entry), install_dir, "temp")
            if not os.listdir(update_tmp_parent):
                _safe_remove_dir(update_tmp_parent, install_dir, "temp parent")
    except Exception as e:
        log.debug("Failed to clean update temp parent: %s", e)

    try:
        temp_dir = tempfile.gettempdir()
        for entry in os.listdir(temp_dir):
            if entry.startswith("BlindRSS_update_"):
                candidate = os.path.join(temp_dir, entry)
                _safe_remove_dir(candidate, install_dir, "temp")
    except Exception as e:
        log.debug("Failed to clean system temp updates: %s", e)


def download_and_apply_update(info: UpdateInfo, debug_mode: bool = False) -> Tuple[bool, str]:
    if not is_update_supported():
        return False, "Auto-update is only available in the packaged Windows build."

    install_dir = APP_DIR
    helper_path = os.path.join(install_dir, "update_helper.bat")
    if not os.path.isfile(helper_path):
        return False, "update_helper.bat is missing from the install directory."

    temp_root = _make_update_temp_root(install_dir)
    zip_path = os.path.join(temp_root, info.asset_name)
    extract_dir = os.path.join(temp_root, "extract")
    os.makedirs(extract_dir, exist_ok=True)

    try:
        resp = safe_requests_get(info.download_url, stream=True, timeout=30)
        resp.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        return False, f"Failed to download update: {e}"

    digest = _sha256_file(zip_path)
    if digest.lower() != info.sha256.lower():
        return False, "Downloaded update failed SHA-256 verification."

    try:
        _extract_zip(zip_path, extract_dir)
    except Exception as e:
        return False, f"Failed to extract update: {e}"

    staging_root = _find_staging_root(extract_dir)
    exe_path = os.path.join(staging_root, EXE_NAME)
    if not os.path.isfile(exe_path):
        return False, f"Update package is missing {EXE_NAME}."

    ok, msg = _verify_authenticode_signature(exe_path, info.signing_thumbprints)
    if not ok:
        return False, msg

    helper_run_path = helper_path
    try:
        helper_temp = os.path.join(temp_root, "update_helper.bat")
        shutil.copy2(helper_path, helper_temp)
        helper_run_path = helper_temp
    except Exception:
        helper_run_path = helper_path

    show_log = False
    try:
        raw_show = os.environ.get("BLINDRSS_UPDATE_SHOW_WINDOW", "0")
        if str(raw_show).strip().lower() in ("1", "true", "yes", "on"):
            show_log = True
    except Exception:
        show_log = False
    if debug_mode:
        show_log = False

    ok, msg = _launch_update_helper(
        helper_run_path,
        os.getpid(),
        install_dir,
        staging_root,
        temp_root=temp_root,
        debug_mode=debug_mode,
        show_log=show_log,
    )
    if not ok:
        return False, msg

    return True, "Update prepared. The app will restart after it exits."
