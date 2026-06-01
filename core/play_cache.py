"""Management for the YouTube playback download cache (`ytplay_cache`).

When the bundled VLC cannot stream a resolved googlevideo URL, BlindRSS downloads
the audio to this cache and plays it as a local file. These helpers resolve the
cache location (default beside the data dir, or a user-chosen folder), report and
clear its size, and prune it to a configured cap so it never grows without bound.

GUI-free and unit tested so the Settings dialog and the player can share it.
"""

from __future__ import annotations

import os

DEFAULT_DIRNAME = "ytplay_cache"
# Files that are mid-download / sidecar and must not be counted or replayed.
_SKIP_SUFFIXES = (".part", ".ytdl", ".tmp")


def default_cache_dir() -> str:
    """Default cache location: a folder beside config.json / rss.db."""
    try:
        from core.config import get_data_dir
        base = get_data_dir()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), ".blindrss")
    return os.path.join(base, DEFAULT_DIRNAME)


def resolve_cache_dir(config_manager) -> str:
    """The active cache dir: the user's chosen folder, else the default."""
    custom = ""
    try:
        custom = str(config_manager.get("youtube_play_cache_dir", "") or "").strip()
    except Exception:
        custom = ""
    return custom or default_cache_dir()


def ensure_cache_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def _cache_files(cache_dir: str) -> list[str]:
    out: list[str] = []
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return out
    for n in names:
        if n.endswith(_SKIP_SUFFIXES):
            continue
        p = os.path.join(cache_dir, n)
        if os.path.isfile(p):
            out.append(p)
    return out


def cache_size_bytes(cache_dir: str) -> int:
    total = 0
    for p in _cache_files(cache_dir):
        try:
            total += os.path.getsize(p)
        except OSError:
            pass
    return total


def cache_file_count(cache_dir: str) -> int:
    return len(_cache_files(cache_dir))


def clear_cache(cache_dir: str) -> tuple[int, int]:
    """Delete every file in the cache (incl. partial/sidecar files).

    Returns (files_removed, bytes_freed).
    """
    removed = 0
    freed = 0
    try:
        names = os.listdir(cache_dir)
    except OSError:
        return 0, 0
    for n in names:
        p = os.path.join(cache_dir, n)
        if not os.path.isfile(p):
            continue
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        try:
            os.remove(p)
            removed += 1
            freed += size
        except OSError:
            pass
    return removed, freed


def prune_cache(cache_dir: str, max_mb) -> int:
    """Delete oldest files until total size is within max_mb. Returns count removed.

    max_mb <= 0 means unlimited (no pruning).
    """
    try:
        max_bytes = int(max_mb) * 1024 * 1024
    except (TypeError, ValueError):
        return 0
    if max_bytes <= 0:
        return 0
    files = _cache_files(cache_dir)
    try:
        # Newest first; keep newest, drop oldest once we exceed the cap.
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    except OSError:
        return 0
    removed = 0
    total = 0
    for p in files:
        try:
            size = os.path.getsize(p)
        except OSError:
            size = 0
        total += size
        if total > max_bytes:
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    return removed


def human_size(num_bytes) -> str:
    n = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"
