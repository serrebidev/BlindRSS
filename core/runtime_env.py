import os
import sys
from pathlib import Path


def _prepend_env_path(var_name: str, value: str) -> None:
    raw = str(value or "").strip()
    if not raw:
        return
    current = os.environ.get(var_name, "")
    parts = [p for p in current.split(os.pathsep) if p]
    if raw in parts:
        return
    os.environ[var_name] = os.pathsep.join([raw, *parts]) if parts else raw


def _first_existing(paths):
    for path in paths:
        try:
            if path and Path(path).exists():
                return Path(path)
        except Exception:
            continue
    return None


def _candidate_vlc_plugin_dir(base_dir: Path):
    return _first_existing(
        [
            base_dir / "vlc" / "plugins",
            base_dir / "vlc" / "modules",
        ]
    )


def _candidate_vlc_lib_path(base_dir: Path):
    if sys.platform.startswith("darwin"):
        candidates = [
            base_dir / "vlc" / "lib" / "libvlc.dylib",
        ]
    elif sys.platform.startswith("linux"):
        lib_dir = base_dir / "vlc" / "lib"
        candidates = [
            lib_dir / "libvlc.so.5",
            lib_dir / "libvlc.so",
            *sorted(lib_dir.glob("libvlc.so*")),
        ]
    else:
        candidates = [
            base_dir / "vlc" / "libvlc.dll",
            base_dir / "libvlc.dll",
        ]
    return _first_existing(candidates)


def configure_runtime_environment() -> None:
    if not getattr(sys, "frozen", False):
        return

    try:
        base_dir = Path(getattr(sys, "executable", "")).resolve().parent
    except Exception:
        return

    bin_dir = base_dir / "bin"
    if bin_dir.is_dir():
        _prepend_env_path("PATH", str(bin_dir))

    lib_path = _candidate_vlc_lib_path(base_dir)
    plugin_dir = _candidate_vlc_plugin_dir(base_dir)

    if lib_path:
        os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(lib_path))
        if sys.platform.startswith("linux"):
            _prepend_env_path("LD_LIBRARY_PATH", str(lib_path.parent))
        elif sys.platform.startswith("darwin"):
            _prepend_env_path("DYLD_LIBRARY_PATH", str(lib_path.parent))

    if plugin_dir:
        os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(plugin_dir))
