import subprocess
import sys
import importlib.metadata
import shutil
import platform
import os
import ctypes
import time
import tempfile
import zipfile
from pathlib import Path

try:
    import winreg
except Exception:
    winreg = None

def _dependency_log_path():
    temp_dir = os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))
    return os.path.join(temp_dir, "blindrss_dep_check.log")

def get_dependency_log_path():
    return _dependency_log_path()

def _log(msg):
    """Write to a persistent log file in temp dir for user diagnostics."""
    try:
        t = time.strftime("%Y-%m-%d %H:%M:%S")
        log_path = _dependency_log_path()
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"[{t}] {msg}\n")
    except:
        pass

def _get_startup_info():
    """Helper to get a hidden startup info object for Windows."""
    if platform.system().lower() != "windows":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0 # SW_HIDE
    return si

def _run_quiet(cmd, timeout=900):
    """Run command and log output to persistent log file."""
    _log(f"Running command: {' '.join(cmd)}")
    creationflags = 0
    if platform.system().lower() == "windows":
        creationflags = 0x08000000 # CREATE_NO_WINDOW
    
    out_file = tempfile.TemporaryFile(mode='w+')
    try:
        res = subprocess.run(
            cmd,
            stdout=out_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            timeout=timeout,
            creationflags=creationflags,
            startupinfo=_get_startup_info(),
            check=False,
            text=True,
            encoding='utf-8', 
            errors='replace'
        )
        out_file.seek(0)
        output = out_file.read()
        if output.strip():
            _log(f"Output:\n{output}")
            
        if res.returncode != 0:
            _log(f"Command failed with rc={res.returncode}")
        return res.returncode
    except Exception as e:
        _log(f"Command execution failed: {e}")
        return None
    finally:
        out_file.close()

def _normalize_path_entry(path):
    if not path:
        return ""
    try:
        expanded = os.path.expandvars(str(path)).strip().strip('"')
        return os.path.normcase(os.path.abspath(expanded))
    except Exception:
        return str(path).strip().strip('"').lower()

def _add_bin_to_process_path(bin_dir):
    if not bin_dir:
        return
    try:
        bin_dir = os.path.abspath(bin_dir)
    except Exception:
        return
    current = os.environ.get("PATH", "")
    parts = [p.strip().strip('"') for p in current.split(os.pathsep) if p.strip()]
    norm_parts = [_normalize_path_entry(p) for p in parts]
    norm_bin = _normalize_path_entry(bin_dir)
    if norm_bin in norm_parts:
        return
    os.environ["PATH"] = os.pathsep.join([bin_dir] + parts)

def _broadcast_env_change():
    if platform.system().lower() != "windows":
        return
    try:
        hwnd_broadcast = 0xFFFF
        wm_settingchange = 0x001A
        smto_abortifhung = 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            hwnd_broadcast,
            wm_settingchange,
            0,
            "Environment",
            smto_abortifhung,
            5000,
            ctypes.byref(result),
        )
    except Exception as e:
        _log(f"Failed to broadcast env change: {e}")


def _runtime_search_roots():
    roots = []
    if getattr(sys, "frozen", False):
        try:
            exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        except Exception:
            exe_dir = ""
        if exe_dir:
            roots.append(exe_dir)
            if platform.system().lower() == "darwin":
                roots.append(os.path.join(os.path.dirname(exe_dir), "Frameworks"))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            roots.append(meipass)
    else:
        roots.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    unique = []
    seen = set()
    for root in roots:
        if not root:
            continue
        norm = _normalize_path_entry(root)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(root)
    return unique


def _candidate_vlc_lib_paths():
    system_name = platform.system().lower()
    candidates = []
    for root in _runtime_search_roots():
        root_path = Path(root)
        if system_name == "darwin":
            candidates.extend(
                [
                    root_path / "vlc" / "lib" / "libvlc.dylib",
                    Path("/Applications/VLC.app/Contents/MacOS/lib/libvlc.dylib"),
                    Path.home() / "Applications" / "VLC.app" / "Contents" / "MacOS" / "lib" / "libvlc.dylib",
                ]
            )
        elif system_name == "linux":
            lib_dir = root_path / "vlc" / "lib"
            candidates.extend(
                [
                    lib_dir / "libvlc.so.5",
                    lib_dir / "libvlc.so",
                    *sorted(lib_dir.glob("libvlc.so*")),
                ]
            )
        else:
            candidates.extend(
                [
                    root_path / "vlc" / "libvlc.dll",
                    root_path / "libvlc.dll",
                ]
            )
    return [str(path) for path in candidates if path and path.is_file()]

def _maybe_add_windows_path():
    """Meticulously find VLC/ffmpeg/yt-dlp and add to PATH for this process."""
    if platform.system().lower() != "windows":
        return
    if winreg is None:
        return
    
    _log("Starting meticulous Windows path search...")
    candidates = set()
    to_add_front = []
    
    # 0. Check app directory
    app_exe = sys.executable if getattr(sys, 'frozen', False) else __file__
    app_dir = os.path.dirname(os.path.abspath(app_exe))
    candidates.add(app_dir)
    candidates.add(os.path.join(app_dir, "bin"))
    
    # 0.1 General Python Scripts folders (WinGet/Store/Installer locations)
    # Use environment variables to avoid hardcoded user names
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        # Check common Python versions in Programs/Python
        programs_python = os.path.join(local_app_data, "Programs", "Python")
        if os.path.isdir(programs_python):
            try:
                for d in os.listdir(programs_python):
                    scripts = os.path.join(programs_python, d, "Scripts")
                    if os.path.isdir(scripts):
                        to_add_front.append(scripts)
                        candidates.add(scripts)
            except: pass
        candidates.update([
            os.path.join(local_app_data, r"Programs\ffmpeg\bin"),
            os.path.join(local_app_data, r"Programs\FFmpeg\bin"),
            os.path.join(local_app_data, r"Programs\Gyan\FFmpeg\bin"),
            os.path.join(local_app_data, r"Programs\VideoLAN\VLC"),
            os.path.join(local_app_data, r"Programs\VLC"),
            os.path.join(local_app_data, r"Programs\yt-dlp"),
            os.path.join(local_app_data, r"Programs\yt-dlp\bin"),
            os.path.join(local_app_data, r"Microsoft\WindowsApps"),
        ])

    # 1. Common hardcoded paths
    candidates.update([
        r"C:\Program Files\VideoLAN\VLC",
        r"C:\Program Files (x86)\VideoLAN\VLC",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\Program Files (x86)\ffmpeg\bin",
        r"C:\Program Files\Gyan\FFmpeg\bin",
        r"C:\Program Files (x86)\Gyan\FFmpeg\bin",
        r"C:\Program Files\Gyan\FFmpeg",
        r"C:\Program Files (x86)\Gyan\FFmpeg",
        r"C:\ffmpeg\bin",
        r"C:\tools\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
        r"C:\Program Files\Common Files\VLC",
        r"C:\vlc",
        r"D:\ffmpeg\bin",
        r"D:\vlc",
    ])
    
    # 1.1 Read System and User PATH from Registry directly and EXPAND them
    for hive, subkey in [(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                         (winreg.HKEY_CURRENT_USER, r"Environment")]:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                p, _ = winreg.QueryValueEx(key, "PATH")
                if p:
                    expanded_p = os.path.expandvars(str(p))
                    for part in expanded_p.split(os.pathsep):
                        part = part.strip('"').strip()
                        if part: candidates.add(part)
        except: pass
    
    # 2. Registry - Specific App Keys
    vlc_registry_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VideoLAN\VLC"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\VideoLAN\VLC"),
    ]
    
    for hive, subkey in vlc_registry_paths:
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | view) as key:
                    for val_name in ("InstallDir", "InstallLocation"):
                        try:
                            p, _ = winreg.QueryValueEx(key, val_name)
                            if p: 
                                p_exp = os.path.expandvars(str(p))
                                candidates.add(p_exp)
                                candidates.add(os.path.join(p_exp, "bin"))
                        except: pass
            except: pass

    # 3. Registry - App Paths
    for app in ("vlc.exe", "ffmpeg.exe"):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{app}") as key:
                p, _ = winreg.QueryValueEx(key, "")
                if p:
                    p_exp = os.path.expandvars(str(p))
                    candidates.add(os.path.dirname(p_exp))
        except: pass

    # 4. Registry - Uninstall Keys
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for root in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                     r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
            try:
                with winreg.OpenKey(hive, root) as key:
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        try:
                            name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, name) as item:
                                try:
                                    disp, _ = winreg.QueryValueEx(item, "DisplayName")
                                    disp_l = str(disp).lower()
                                    if "vlc" in disp_l or "ffmpeg" in disp_l:
                                        loc, _ = winreg.QueryValueEx(item, "InstallLocation")
                                        if loc:
                                            loc_exp = os.path.expandvars(str(loc))
                                            candidates.add(loc_exp)
                                            candidates.add(os.path.join(loc_exp, "bin"))
                                except: pass
                        except: pass
            except: pass

    # 5. User-space (Scoop, WinGet)
    user_p = os.environ.get("USERPROFILE", "")
    if user_p:
        candidates.update([
            os.path.join(user_p, r"scoop\shims"),
            os.path.join(user_p, r"scoop\apps\ffmpeg\current\bin"),
            os.path.join(user_p, r"scoop\apps\vlc\current"),
            os.path.join(user_p, r"AppData\Local\Microsoft\WinGet\Packages"),
            os.path.join(user_p, r"AppData\Local\Microsoft\WinGet\Links"),
        ])

    # 6. Scan WinGet Packages root specifically
    if local_app_data:
        winget_root = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_root):
            try:
                for d in os.listdir(winget_root):
                    if "vlc" in d.lower() or "ffmpeg" in d.lower() or "yt-dlp" in d.lower():
                        base = os.path.join(winget_root, d)
                        candidates.add(base)
                        for root, dirs, files in os.walk(base):
                            if (
                                "ffmpeg.exe" in files
                                or "vlc.exe" in files
                                or "libvlc.dll" in files
                                or "yt-dlp.exe" in files
                            ):
                                candidates.add(root)
                                break
            except: pass

    # 7. Add to process PATH
    current_path = os.environ.get("PATH", "")
    current_paths_lower = [p.lower().strip('"').strip() for p in current_path.split(os.pathsep) if p.strip()]
    
    to_add = []
    # Add front-prioritized candidates first
    for p in to_add_front:
        if p and os.path.isdir(p):
            p_abs = os.path.abspath(p)
            if p_abs.lower() not in current_paths_lower:
                to_add.append(p_abs)
                current_paths_lower.append(p_abs.lower())

    for p in candidates:
        if p and os.path.isdir(p):
            p_abs = os.path.abspath(p)
            if p_abs.lower() not in current_paths_lower:
                to_add.append(p_abs)
                current_paths_lower.append(p_abs.lower())
    
    if to_add:
        _log(f"Adding to PATH: {';'.join(to_add)}")
        os.environ["PATH"] = os.pathsep.join(to_add + [current_path])
    
    # 8. Explicitly set VLC lib path if found
    for p in candidates:
        if p and os.path.isdir(p):
            dll = os.path.join(p, "libvlc.dll")
            if os.path.isfile(dll):
                _log(f"Found libvlc.dll at {dll}")
                os.environ["PYTHON_VLC_LIB_PATH"] = dll
                if hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(p)
                    except: pass
                break

def _collect_tool_candidates(tool_name):
    tool = str(tool_name).lower().replace(".exe", "")
    dirs = set()
    search_roots = set()
    runtime_roots = _runtime_search_roots()
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    program_w6432 = os.environ.get("ProgramW6432", "")
    user_p = os.environ.get("USERPROFILE", "")
    choco_root = os.environ.get("ChocolateyInstall", r"C:\ProgramData\chocolatey")

    if user_p:
        dirs.update([
            os.path.join(user_p, r"scoop\shims"),
            os.path.join(user_p, r"scoop\apps\ffmpeg\current\bin"),
            os.path.join(user_p, r"scoop\apps\vlc\current"),
        ])

    for root in runtime_roots:
        dirs.add(root)
        dirs.add(os.path.join(root, "bin"))
        if tool == "vlc":
            dirs.add(os.path.join(root, "vlc"))
            dirs.add(os.path.join(root, "vlc", "bin"))
            search_roots.add(os.path.join(root, "vlc"))

    if tool == "vlc":
        for base in (program_w6432, program_files, program_files_x86):
            if base:
                dirs.add(os.path.join(base, "VideoLAN", "VLC"))
        if local_app_data:
            dirs.add(os.path.join(local_app_data, "Programs", "VideoLAN", "VLC"))
            dirs.add(os.path.join(local_app_data, "Programs", "VLC"))
        dirs.update([
            r"C:\Program Files\VideoLAN\VLC",
            r"C:\Program Files (x86)\VideoLAN\VLC",
            r"C:\Program Files\Common Files\VLC",
            r"C:\vlc",
            r"D:\vlc",
        ])
        if choco_root:
            dirs.add(os.path.join(choco_root, "lib", "vlc", "tools"))
            dirs.add(os.path.join(choco_root, "bin"))
        if platform.system().lower() == "darwin":
            dirs.add("/Applications/VLC.app/Contents/MacOS")
            dirs.add(os.path.join(os.path.expanduser("~/Applications"), "VLC.app", "Contents", "MacOS"))

    if tool == "ffmpeg":
        for base in (program_w6432, program_files, program_files_x86):
            if base:
                dirs.add(os.path.join(base, "Gyan", "FFmpeg", "bin"))
                dirs.add(os.path.join(base, "FFmpeg", "bin"))
                dirs.add(os.path.join(base, "ffmpeg", "bin"))
        if local_app_data:
            dirs.add(os.path.join(local_app_data, "Programs", "ffmpeg", "bin"))
            dirs.add(os.path.join(local_app_data, "Programs", "FFmpeg", "bin"))
            dirs.add(os.path.join(local_app_data, "Programs", "Gyan", "FFmpeg", "bin"))
            search_roots.add(os.path.join(local_app_data, "BlindRSS", "ffmpeg", "extract"))
        dirs.update([
            r"C:\Program Files\Gyan\FFmpeg\bin",
            r"C:\Program Files (x86)\Gyan\FFmpeg\bin",
            r"C:\Program Files\ffmpeg\bin",
            r"C:\Program Files (x86)\ffmpeg\bin",
            r"C:\ffmpeg\bin",
            r"C:\tools\ffmpeg\bin",
            r"D:\ffmpeg\bin",
        ])
        if choco_root:
            dirs.add(os.path.join(choco_root, "bin"))
            dirs.add(os.path.join(choco_root, "lib", "ffmpeg", "tools", "ffmpeg", "bin"))

    if tool == "yt-dlp":
        base_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        dirs.add(os.path.join(base_dir, "bin"))
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            dirs.add(os.path.join(sys._MEIPASS, "bin"))
        if local_app_data:
            dirs.add(os.path.join(local_app_data, "Programs", "yt-dlp"))
            dirs.add(os.path.join(local_app_data, "Programs", "yt-dlp", "bin"))
            dirs.add(os.path.join(local_app_data, "Microsoft", "WinGet", "Links"))
            dirs.add(os.path.join(local_app_data, "Microsoft", "WindowsApps"))
        if choco_root:
            dirs.add(os.path.join(choco_root, "bin"))

    if local_app_data:
        winget_root = os.path.join(local_app_data, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(winget_root):
            search_roots.add(winget_root)

    return dirs, search_roots

def _find_executable_path(exe_name, extra_dirs=None):
    exe_base = str(exe_name).strip()
    if not exe_base:
        return None
    system_name = platform.system().lower()
    exe_candidates = []
    if exe_base:
        exe_candidates.append(exe_base)
    if system_name == "windows":
        if not exe_base.lower().endswith(".exe"):
            exe_candidates.append(f"{exe_base}.exe")
    elif exe_base.lower().endswith(".exe"):
        exe_candidates.append(exe_base[:-4])
    exe_candidates = [candidate for i, candidate in enumerate(exe_candidates) if candidate and candidate not in exe_candidates[:i]]

    try:
        _maybe_add_windows_path()
    except Exception:
        pass

    for candidate in exe_candidates:
        exe = shutil.which(candidate)
        if exe and os.path.isfile(exe):
            return exe

    if system_name == "windows":
        try:
            res = subprocess.run(
                ["where", exe_base],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                creationflags=0x08000000,
                startupinfo=_get_startup_info(),
                timeout=5
            )
            if res.returncode == 0 and res.stdout:
                first_found = res.stdout.splitlines()[0].strip()
                if os.path.isfile(first_found):
                    return first_found
        except Exception:
            pass

    candidates, search_roots = _collect_tool_candidates(exe_base)
    if extra_dirs:
        for d in extra_dirs:
            if d:
                candidates.add(d)

    for d in candidates:
        if not d:
            continue
        try:
            d_abs = os.path.abspath(d)
        except Exception:
            d_abs = d
        for exe_file in exe_candidates:
            exe_path = os.path.join(d_abs, exe_file)
            if os.path.isfile(exe_path):
                return exe_path

    for root in search_roots:
        if not root or not os.path.isdir(root):
            continue
        try:
            for cur_root, _, files in os.walk(root):
                for exe_file in exe_candidates:
                    if exe_file in files:
                        return os.path.join(cur_root, exe_file)
        except Exception:
            continue

    return None

def _set_vlc_lib_path(vlc_dir):
    if not vlc_dir:
        return
    dll = os.path.join(vlc_dir, "libvlc.dll")
    if os.path.isfile(dll):
        os.environ["PYTHON_VLC_LIB_PATH"] = dll
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(vlc_dir)
            except Exception:
                pass

def _ensure_tool_on_path(tool_name):
    exe_path = _find_executable_path(tool_name)
    if not exe_path:
        return False
    bin_dir = os.path.dirname(exe_path)
    _add_bin_to_process_path(bin_dir)
    _add_bin_to_user_path(bin_dir)
    if str(tool_name).lower().startswith("vlc"):
        _set_vlc_lib_path(bin_dir)
    return True

def _should_check_updates(marker_name):
    """Throttles specific checks to once every 24 hours."""
    temp_dir = os.environ.get("TEMP", os.environ.get("TMP", tempfile.gettempdir()))
    marker = os.path.join(temp_dir, f"blindrss_last_{marker_name}.txt")
    try:
        if os.path.isfile(marker):
            mtime = os.path.getmtime(marker)
            if (time.time() - mtime) < 86400:
                _log(f"Throttle active for {marker_name} (last check: {time.ctime(mtime)})")
                return False
        with open(marker, "w") as f:
            f.write(str(time.time()))
    except: pass
    return True

def has(cmd, version_arg="-version"):
    """Robust verification of executable availability."""
    # 1. Check PATH via shutil.which
    exe = shutil.which(cmd) or shutil.which(f"{cmd}.exe")
    if exe:
        if os.path.isfile(exe):
            _log(f"Found {cmd} at {exe} via which.")
            return True

    if platform.system().lower() == "windows":
        try:
            # 2. Use 'where' command as a fallback
            res = subprocess.run(
                ["where", cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                text=True,
                creationflags=0x08000000,
                startupinfo=_get_startup_info(),
                timeout=5
            )
            if res.returncode == 0 and res.stdout:
                first_found = res.stdout.splitlines()[0].strip()
                if os.path.isfile(first_found):
                    _log(f"'where' found {cmd} at {first_found}")
                    return True
        except: pass
    return False

def _has_winget():
    if platform.system().lower() != "windows":
        return False
    exe = shutil.which("winget") or shutil.which("winget.exe")
    if exe:
        return True
    try:
        res = subprocess.run(
            ["winget", "--version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
            startupinfo=_get_startup_info(),
            timeout=5
        )
        return res.returncode == 0
    except Exception:
        return False

def _winget_install(package_id, scope=None):
    if platform.system().lower() != "windows":
        return False
    if not _has_winget():
        _log("Winget not available.")
        return False
    cmd = ["winget", "install", "-e", "--id", package_id]
    cmd += ["--accept-package-agreements", "--accept-source-agreements", "--no-upgrade", "--disable-interactivity"]
    if scope:
        cmd += ["--scope", scope]
    rc = _run_quiet(cmd)
    if rc == 0:
        return True
    _log(f"Winget install failed for {package_id} with rc={rc}")
    return False

def _download_file(url, dest_path):
    try:
        from core import utils
        resp = utils.safe_requests_get(url, stream=True, timeout=30)
        resp.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        _log(f"Download failed ({url}): {e}")
        return False

def _install_vlc_fallback():
    if platform.system().lower() != "windows":
        return False
    # Use a specific version to ensure stability and a predictable URL. 
    # VLC 3.0.21 is a recent stable release for 64-bit Windows.
    url = "https://get.videolan.org/vlc/3.0.21/win64/vlc-3.0.21-win64.exe"
    temp_dir = tempfile.gettempdir()
    exe_path = os.path.join(temp_dir, f"BlindRSS_VLC_Install_{os.getpid()}.exe")
    _log(f"Downloading VLC from {url}...")
    if not _download_file(url, exe_path):
        return False
    
    # Run silently
    # /S = Silent, /L=1033 = English
    _log("Running VLC installer silently...")
    rc = _run_quiet([exe_path, "/L=1033", "/S"])
    if rc == 0:
        return True
    _log(f"VLC install failed with rc={rc}")
    return False

def _install_ffmpeg_fallback():
    if platform.system().lower() != "windows":
        return False
    url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    local_app_data = os.environ.get("LOCALAPPDATA", tempfile.gettempdir())
    base_dir = os.path.join(local_app_data, "BlindRSS", "ffmpeg")
    os.makedirs(base_dir, exist_ok=True)
    zip_path = os.path.join(base_dir, "ffmpeg.zip")
    if not _download_file(url, zip_path):
        return False
    extract_dir = os.path.join(base_dir, "extract")
    try:
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except Exception as e:
        _log(f"Failed to extract ffmpeg zip: {e}")
        return False
    ffmpeg_dir = None
    try:
        for root, _, files in os.walk(extract_dir):
            if "ffmpeg.exe" in files:
                ffmpeg_dir = root
                break
    except Exception as e:
        _log(f"Failed to locate ffmpeg.exe: {e}")
    if not ffmpeg_dir:
        _log("ffmpeg.exe not found after extraction.")
        return False
    _add_bin_to_user_path(ffmpeg_dir)
    current = os.environ.get("PATH", "")
    if ffmpeg_dir not in current.split(os.pathsep):
        os.environ["PATH"] = os.pathsep.join([ffmpeg_dir, current])
    _log(f"Installed ffmpeg fallback to {ffmpeg_dir}")
    return True

def _is_ytdlp_available():
    return _find_executable_path("yt-dlp") is not None

def _winget_has_package(package_id):
    """Check if winget thinks the package is already installed."""
    if platform.system().lower() != "windows":
        return False
    if not _has_winget():
        return False
    try:
        # Use 'winget list --id <id>' to check for existence
        res = subprocess.run(
            ["winget", "list", "--id", package_id, "--source", "winget"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=0x08000000,
            startupinfo=_get_startup_info(),
            timeout=15
        )
        if res.returncode == 0 and package_id.lower() in res.stdout.decode('utf-8', 'ignore').lower():
            _log(f"Winget reports package {package_id} is already installed.")
            return True
    except: 
        pass
    return False

def check_media_tools_status():
    """Returns tuple (vlc_missing, ffmpeg_missing, ytdlp_missing)."""
    _maybe_add_windows_path()

    vlc_exe = _find_executable_path("vlc")
    if vlc_exe:
        vlc_present = True
        _add_bin_to_process_path(os.path.dirname(vlc_exe))
        _set_vlc_lib_path(os.path.dirname(vlc_exe))
    else:
        vlc_present = False
        if os.environ.get("PYTHON_VLC_LIB_PATH") and os.path.isfile(os.environ["PYTHON_VLC_LIB_PATH"]):
            vlc_present = True
        if not vlc_present:
            vlc_lib_candidates = _candidate_vlc_lib_paths()
            if vlc_lib_candidates:
                vlc_present = True
                os.environ.setdefault("PYTHON_VLC_LIB_PATH", vlc_lib_candidates[0])
        if not vlc_present and _winget_has_package("VideoLAN.VLC"):
            vlc_present = True

    ffmpeg_exe = _find_executable_path("ffmpeg")
    if ffmpeg_exe:
        ff_present = True
        _add_bin_to_process_path(os.path.dirname(ffmpeg_exe))
    else:
        ff_present = False
        if _winget_has_package("Gyan.FFmpeg"):
            ff_present = True

    ytdlp_exe = _find_executable_path("yt-dlp")
    if ytdlp_exe:
        ytdlp_present = True
        _add_bin_to_process_path(os.path.dirname(ytdlp_exe))
    else:
        ytdlp_present = False
        if _winget_has_package("yt-dlp.yt-dlp"):
            ytdlp_present = True

    return (not vlc_present, not ff_present, not ytdlp_present)

def _wait_for_executable(tool_name, timeout=30):
    """Polls for the executable to appear on the system."""
    start = time.time()
    while (time.time() - start) < timeout:
        if _find_executable_path(tool_name):
            return True
        time.sleep(1)
    return False

def install_media_tools(vlc=True, ffmpeg=True, ytdlp=False):
    """Installs missing tools via winget (Windows only)."""
    if platform.system().lower() != "windows":
        return

    def _winget_install_with_fallback(package_id):
        if _winget_install(package_id, scope="user"):
            return True
        return _winget_install(package_id)

    winget_ok = _has_winget()

    if vlc:
        if winget_ok:
            _log("Installing VLC via winget...")
            if not _winget_install_with_fallback("VideoLAN.VLC"):
                _log("Winget VLC install failed; trying direct download.")
                _install_vlc_fallback()
            elif not _wait_for_executable("vlc"):
                 _log("Winget reported success but VLC not found; trying direct download.")
                 _install_vlc_fallback()
        else:
            _log("Winget unavailable; trying direct download for VLC.")
            _install_vlc_fallback()
        
        # Final check for VLC
        if not _wait_for_executable("vlc"):
            _log("VLC installation verification failed.")

    if ffmpeg:
        if winget_ok:
            _log("Installing FFmpeg via winget...")
            if not _winget_install_with_fallback("Gyan.FFmpeg"):
                _log("Winget FFmpeg install failed; trying fallback download.")
                _install_ffmpeg_fallback()
            elif not _wait_for_executable("ffmpeg"):
                 _log("Winget reported success but FFmpeg not found; trying fallback download.")
                 _install_ffmpeg_fallback()
        else:
            _log("Winget unavailable; trying FFmpeg fallback download.")
            _install_ffmpeg_fallback()
            
        # Final check for FFmpeg
        if not _wait_for_executable("ffmpeg"):
             _log("FFmpeg installation verification failed.")

    if ytdlp:
        if winget_ok:
            _log("Installing yt-dlp via winget...")
            if not _winget_install_with_fallback("yt-dlp.yt-dlp"):
                 _log("Winget yt-dlp install failed; ensuring standalone binary.")
                 _ensure_yt_dlp_cli()
            elif not _wait_for_executable("yt-dlp"):
                 _log("Winget reported success but yt-dlp not found; ensuring standalone binary.")
                 _ensure_yt_dlp_cli()
            else:
                 _ensure_yt_dlp_cli() 
        else:
            _log("Winget unavailable; ensuring standalone yt-dlp binary.")
            _ensure_yt_dlp_cli()
            
        # Final check for yt-dlp
        if not _wait_for_executable("yt-dlp"):
             _log("yt-dlp installation verification failed.")

    _maybe_add_windows_path()

    if vlc:
        _ensure_tool_on_path("vlc")
    if ffmpeg:
        _ensure_tool_on_path("ffmpeg")
    if ytdlp:
        _ensure_tool_on_path("yt-dlp")

def ensure_media_tools():
    """Robust detection of media tools (Path setup only)."""
    _maybe_add_windows_path()
    # Automatic installation has been moved to interactive prompt in GUI.
    return

def _ensure_yt_dlp_cli():
    """Throttled update/install of yt-dlp binary. Prioritizes working version."""
    if platform.system().lower() != "windows":
        return

    base_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    bin_dir = os.path.join(base_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    local_exe = os.path.join(bin_dir, "yt-dlp.exe")

    def works(path):
        try:
            res = subprocess.run(
                [path, "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=0x08000000,
                startupinfo=_get_startup_info(),
                timeout=5
            )
            return res.returncode == 0
        except:
            return False

    # Check for working yt-dlp
    exe = None

    # 0. Check bundled (sys._MEIPASS) if frozen
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        bundled_bin = os.path.join(sys._MEIPASS, "bin")
        bundled_exe = os.path.join(bundled_bin, "yt-dlp.exe")
        if os.path.isfile(bundled_exe) and works(bundled_exe):
            _log(f"Using bundled yt-dlp at {bundled_exe}")
            # Prepend to PATH immediately so subprocess calls find it
            current_path = os.environ.get("PATH", "")
            if bundled_bin not in current_path:
                os.environ["PATH"] = os.pathsep.join([bundled_bin, current_path])
            return

    if os.path.isfile(local_exe) and works(local_exe):
        exe = local_exe
        _log(f"Using local yt-dlp at {exe}")
    else:
        system_exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
        if system_exe and works(system_exe):
            exe = system_exe
            _log(f"Using system yt-dlp at {exe}")

    if exe:
        if _should_check_updates("ytdlp_cli_update"):
            _log("Updating yt-dlp CLI...")
            _run_quiet([exe, "-U"])
        _add_bin_to_user_path(bin_dir)
        return

    # Download if missing
    _log("No working yt-dlp CLI found. Downloading standalone...")
    try:
        url = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
        if not _download_file(url, local_exe):
            raise RuntimeError("yt-dlp download failed")
        _log(f"Downloaded yt-dlp to {local_exe}")
    except Exception as e:
        _log(f"Failed to download yt-dlp: {e}")
        return
    
    current = os.environ.get("PATH", "")
    if bin_dir not in current.split(os.pathsep):
        os.environ["PATH"] = os.pathsep.join([bin_dir, current])
    _add_bin_to_user_path(bin_dir)

def _add_bin_to_user_path(bin_dir):
    """Persist bin_dir to user PATH."""
    try:
        if platform.system().lower() != "windows":
            return
        if winreg is None:
            return
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment", 0, winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            try:
                existing, type_id = winreg.QueryValueEx(key, "PATH")
            except Exception:
                existing = ""
                type_id = winreg.REG_EXPAND_SZ

            # Windows PATH separator is always ';' — do not use os.pathsep,
            # which is ':' on POSIX and would corrupt the registry value if
            # this code path is ever driven from a non-Windows host.
            existing_parts = [p for p in str(existing).split(";") if p]
            norm_existing = {_normalize_path_entry(p) for p in existing_parts}
            norm_bin = _normalize_path_entry(bin_dir)

            if norm_bin in norm_existing:
                return

            # Append to end
            new_path_str = ";".join(existing_parts + [str(bin_dir)])
            
            # Preserve type if it was REG_SZ, otherwise default to REG_EXPAND_SZ
            if type_id not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                type_id = winreg.REG_EXPAND_SZ

            winreg.SetValueEx(key, "PATH", 0, type_id, new_path_str)
            _log(f"Added {bin_dir} to user PATH registry.")
            _broadcast_env_change()
    except Exception as e:
        _log(f"Failed to add to user PATH registry: {e}")

def check_and_install_dependencies():
    """Main dependency check entry point."""
    _log("--- Dependency Check Started ---")
    if getattr(sys, "frozen", False):
        _maybe_add_windows_path()
        _ensure_yt_dlp_cli()
        try: ensure_media_tools()
        except: pass
        _log("--- Dependency Check Finished (Frozen) ---")
        return

    required = {
        'yt-dlp', 'wxpython', 'feedparser', 'requests', 'beautifulsoup4',
        'python-dateutil', 'mutagen', 'python-vlc',
        'pychromecast', 'async-upnp-client', 'pyatv', 'trafilatura',
        'webrtcvad', 'brotli', 'html5lib', 'lxml', 'packaging'
    }

    def _canon(name):
        return (name or "").lower().replace("_", "-")

    # Distributions that satisfy another required name (e.g. webrtcvad-wheels ships the `webrtcvad` module).
    equivalents = {
        'webrtcvad-wheels': 'webrtcvad',
    }

    installed = set()
    for d in importlib.metadata.distributions():
        raw = d.metadata.get("Name") or d.name
        if not raw:
            continue
        canon = _canon(raw)
        installed.add(canon)
        if canon in equivalents:
            installed.add(equivalents[canon])

    missing = {pkg for pkg in required if _canon(pkg) not in installed}

    if missing:
        _log(f"Missing pip packages: {missing}. Installing...")
        try:
            creationflags = 0
            if platform.system().lower() == "windows":
                creationflags = 0x08000000
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--quiet', '--no-python-version-warning', *missing],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=creationflags, startupinfo=_get_startup_info()
            )
            _log("Pip install successful.")
        except Exception as e:
            _log(f"Pip install failed: {e}")

    if _should_check_updates("pip_upgrade"):
        _log("Checking for pip self-upgrade...")
        try:
            creationflags = 0
            if platform.system().lower() == "windows":
                creationflags = 0x08000000
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--upgrade', '--quiet', 'pip'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=creationflags, startupinfo=_get_startup_info()
            )
        except: pass

    if _should_check_updates("ytdlp_pip_upgrade"):
        _log("Checking for yt-dlp pip upgrade...")
        try:
            creationflags = 0
            if platform.system().lower() == "windows":
                creationflags = 0x08000000
            subprocess.check_call(
                [sys.executable, '-m', 'pip', 'install', '--upgrade', '--quiet', '--no-python-version-warning', 'yt-dlp'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                creationflags=creationflags, startupinfo=_get_startup_info()
            )
        except: pass

    try: ensure_media_tools()
    except: pass
    try: _ensure_yt_dlp_cli()
    except: pass
    _log("--- Dependency Check Finished ---")
