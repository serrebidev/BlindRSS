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


def _runtime_roots(base_dir: Path):
    roots = [base_dir]
    if sys.platform.startswith("darwin"):
        roots.append(base_dir.parent / "Frameworks")

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))

    unique = []
    seen = set()
    for root in roots:
        try:
            resolved = Path(root).resolve()
        except Exception:
            resolved = Path(root)
        key = str(resolved)
        if key in seen:
            continue
        seen.add(key)
        unique.append(resolved)
    return unique


def _candidate_vlc_plugin_dir(base_dir: Path):
    candidates = []
    for root in _runtime_roots(base_dir):
        candidates.extend(
            [
                root / "vlc" / "plugins",
                root / "vlc" / "modules",
            ]
        )
    return _first_existing(candidates)


def _candidate_vlc_lib_path(base_dir: Path):
    candidates = []
    for root in _runtime_roots(base_dir):
        if sys.platform.startswith("darwin"):
            candidates.append(root / "vlc" / "lib" / "libvlc.dylib")
        elif sys.platform.startswith("linux"):
            lib_dir = root / "vlc" / "lib"
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
                    root / "vlc" / "libvlc.dll",
                    root / "libvlc.dll",
                ]
            )
    return _first_existing(candidates)


def configure_runtime_environment() -> None:
    if not getattr(sys, "frozen", False):
        return

    try:
        base_dir = Path(getattr(sys, "executable", "")).resolve().parent
    except Exception:
        return

    for root in _runtime_roots(base_dir):
        bin_dir = root / "bin"
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
