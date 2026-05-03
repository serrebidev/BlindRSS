"""
Range-aware local HTTP proxy with on-disk caching to improve seek performance on
high-latency remote HTTP/HTTPS audio files.

Why this exists:
- VLC seeks over HTTP using Range requests.
- On high-latency connections, each seek can pause while VLC re-requests remote bytes.
- This proxy terminates VLC's HTTP requests locally and serves bytes from a local cache.
- Cache misses are fetched from the origin using larger "prefetch" ranges and stored on disk.

Design notes:
- Cache is stored as chunk files per URL to avoid creating huge sparse files when seeking far ahead.
- Uses requests.Session to reuse TCP/TLS connections (keep-alive) for better latency.
- Provides a /health endpoint so callers can reliably wait for startup.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
import traceback
import os
import re
import threading
import time
import tempfile
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests

from core.utils import HEADERS

LOG = logging.getLogger(__name__)

_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)

# Keep probe timeouts short so initial playback isn't held hostage by slow trackers.
_PROBE_CONNECT_TIMEOUT_S = 3.0
_PROBE_READ_TIMEOUT_S = 8.0
_PROBE_WAIT_S = 3.0

# Cap how much extra we fetch inline (beyond the requested bytes) to keep seeks snappy.
# Larger amounts still happen via background download.
_INLINE_PREFETCH_CAP_BYTES = 16 * 1024 * 1024

_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d+)?$")
_CONTENT_RANGE_RE = re.compile(r"^\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$", re.IGNORECASE)


def _safe_mkdir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", "ignore")).hexdigest()


def _merge_segments(segs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not segs:
        return []
    segs = sorted(segs, key=lambda x: (x[0], x[1]))
    out: List[Tuple[int, int]] = []
    cs, ce = segs[0]
    for s, e in segs[1:]:
        if s <= ce + 1:
            ce = max(ce, e)
        else:
            out.append((cs, ce))
            cs, ce = s, e
    out.append((cs, ce))
    return out


def _normalize_segments(segs: List[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """Normalize on-disk chunk segments.

    Segments correspond 1:1 with cache files named '<start>-<end>.bin'.
    Do NOT merge ranges here, or metadata may point at non-existent files.
    """
    out = set()
    for s, e in (segs or []):
        try:
            s = int(s)
            e = int(e)
        except Exception:
            continue
        if e < s:
            continue
        out.add((s, e))
    return sorted(out, key=lambda x: (x[0], x[1]))


def _missing_segments(have: List[Tuple[int, int]], start: int, end: int) -> List[Tuple[int, int]]:
    if start > end:
        return []
    have = _merge_segments(have)
    missing: List[Tuple[int, int]] = []
    cur = start
    for s, e in have:
        if e < cur:
            continue
        if s > end:
            break
        if s > cur:
            missing.append((cur, min(end, s - 1)))
        cur = max(cur, e + 1)
        if cur > end:
            break
    if cur <= end:
        missing.append((cur, end))
    return missing


def _parse_content_range(value: str) -> Optional[Tuple[int, int, Optional[int]]]:
    # Example: "bytes 0-0/12345" or "bytes 0-0/*"
    if not value:
        return None
    m = _CONTENT_RANGE_RE.match(value)
    if not m:
        return None
    a = int(m.group(1))
    b = int(m.group(2))
    total_raw = m.group(3)
    total = None if total_raw == "*" else int(total_raw)
    return a, b, total


def _parse_range_header(range_value: str, total_length: Optional[int]) -> Optional[Tuple[int, Optional[int]]]:
    # Supports: bytes=start-end, bytes=start-
    if not range_value:
        return None
    range_value = range_value.strip()
    m = _RANGE_RE.match(range_value)
    if not m:
        return None
    start = int(m.group(1))
    end_s = m.group(2)
    if end_s is None or end_s == "":
        # Open-ended range. Leave end unset so the caller can clamp to a
        # smaller inline window for responsive startup.
        return (start, None)
    end = int(end_s)
    if end < start:
        end = start
    if total_length is not None:
        end = min(end, max(start, total_length - 1))
    return (start, end)


class _ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def handle_error(self, request, client_address):
        # VLC/clients often abort local HTTP connections during seek/stop.
        # Treat these as normal and avoid printing noisy tracebacks.
        try:
            _t, exc, _tb = sys.exc_info()
        except Exception:
            exc = None
        if exc is not None:
            if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
                return
            if isinstance(exc, OSError) and getattr(exc, "winerror", None) in (10053, 10054):
                return
        return super().handle_error(request, client_address)


@dataclass
class _Entry:
    url: str
    headers: Dict[str, str]
    cache_dir: str
    prefetch_bytes: int
    initial_burst_bytes: int
    initial_inline_prefetch_bytes: int
    background_download: bool
    background_chunk_bytes: int

    total_length: Optional[int] = None
    content_type: str = "application/octet-stream"
    range_supported: Optional[bool] = None
    segments: List[Tuple[int, int]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    last_access: float = field(default_factory=time.time)

    # Background download state (kept per-entry so early-file caching is stable even if VLC probes the end)
    bg_cursor: int = 0
    bootstrap_done: bool = False
    last_req_start: int = 0
    last_req_time: float = field(default_factory=time.time)

    real_url: Optional[str] = None
    
    # Probe completion event - set once the initial probe finishes
    _probe_done: threading.Event = field(default_factory=threading.Event)

    debug_logs: bool = False
    _dir: str = ""
    _bg_thread: Optional[threading.Thread] = None
    _bg_stop: threading.Event = field(default_factory=threading.Event)

    def __post_init__(self) -> None:
        _safe_mkdir(self.cache_dir)
        self._dir = os.path.join(self.cache_dir, _sha256_hex(self.url))
        _safe_mkdir(self._dir)
        self._load_existing_segments()

    def _debug(self, fmt: str, *args) -> None:
        if not bool(getattr(self, "debug_logs", False)):
            return
        try:
            LOG.info("PROXY_DEBUG: " + fmt, *args)
        except Exception:
            pass

    def _warn(self, fmt: str, *args) -> None:
        try:
            LOG.warning("PROXY_WARNING: " + fmt, *args)
        except Exception:
            pass

    def _make_session(self) -> requests.Session:
        s = requests.Session()
        try:
            # Playback proxying should fail fast. Long retries can stall VLC startup
            # (and are especially painful when combined with redirect chains).
            adapter = requests.adapters.HTTPAdapter(pool_connections=1, pool_maxsize=1, max_retries=0)
            s.mount("http://", adapter)
            s.mount("https://", adapter)
        except Exception:
            pass
        return s

    def touch(self) -> None:
        self.last_access = time.time()

    def _chunk_path(self, start: int, end: int) -> str:
        return os.path.join(self._dir, f"{start:012d}-{end:012d}.bin")

    def _load_existing_segments(self) -> None:
        segs: List[Tuple[int, int]] = []
        try:
            for name in os.listdir(self._dir):
                m = re.match(r"^(\d+)-(\d+)\.bin$", name)
                if not m:
                    continue
                s = int(m.group(1))
                e = int(m.group(2))
                if e >= s:
                    segs.append((s, e))
        except Exception:
            pass
        self.segments = _normalize_segments(segs)

    def _segment_file_is_valid(self, s: int, e: int) -> bool:
        path = self._chunk_path(s, e)
        expected = (e - s + 1)
        if expected <= 0:
            return False
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return False
        except Exception:
            return False
        return st.st_size == expected

    def _prune_bad_segments(self) -> None:
        """
        Drop segment metadata that points at missing or truncated files.
        Now optimized to only run occasionally or on error, rather than every read.
        """
        try:
            with self.lock:
                bad: List[Tuple[int, int]] = []
                # Snapshot list to avoid modification issues while iterating
                current_segs = list(self.segments)
                # Limit check if needed, but for now we rely on lazy detection.
                pass 
        except Exception:
            pass

    def _remove_segment(self, s: int, e: int) -> None:
        """Helper to remove a specific invalid segment."""
        with self.lock:
            try:
                self.segments = [seg for seg in self.segments if seg != (s, e)]
                self.segments = _normalize_segments(self.segments)
            except Exception:
                pass

    def _finalize_chunk(self, temp_path: str, start: int, end: int) -> None:
        """Move temp chunk to final location and update segments."""
        if end < start:
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            return

        final_path = self._chunk_path(start, end)
        try:
            with self.lock:
                if os.path.exists(final_path):
                    # If exact chunk already exists (from another thread), just delete our temp file.
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
                    return

                # Atomic rename if possible (os.replace is atomic on same volume)
                os.replace(temp_path, final_path)
                self._debug("Finalized chunk %s-%s", start, end)
                
                self.segments.append((start, end))
                self.segments = _normalize_segments(self.segments)
        except Exception as e:
            LOG.warning("Failed to finalize chunk %s-%s: %s", start, end, e)
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass

    def probe(self) -> None:
        # Fast path: if already probed, return immediately
        if self._probe_done.is_set():
            return
            
        session = self._make_session()
        try:
            if self.range_supported is not None and (self.total_length is not None or self.range_supported is False):
                self._probe_done.set()
                return

            target_url = self.real_url or self.url

            hdrs = HEADERS.copy()
            hdrs.pop("Accept", None)
            hdrs.update(self.headers or {})
            hdrs.setdefault("User-Agent", _DEFAULT_UA)
            hdrs.setdefault("Accept", "*/*")
            # Avoid transparent compression; ranged fetches must be byte-exact.
            hdrs.setdefault("Accept-Encoding", "identity")
            # Avoid gzip/deflate so byte ranges always map 1:1 to the original file.
            hdrs.setdefault("Accept-Encoding", "identity")

            # Try a single-byte range request (most reliable way to learn length + range support)
            hdrs_probe = dict(hdrs)
            hdrs_probe["Range"] = "bytes=0-0"

            try:
                # allow_redirects=True here; we'll capture the final URL if it changes.
                r = session.get(
                    target_url,
                    headers=hdrs_probe,
                    stream=True,
                    timeout=(_PROBE_CONNECT_TIMEOUT_S, _PROBE_READ_TIMEOUT_S),
                    allow_redirects=True,
                )
            except Exception as e:
                self._warn("RangeCacheProxy probe failed: %s", e)
                self.range_supported = False
                self.total_length = None
                self._probe_done.set()
                return

            try:
                try:
                    final = r.url or ""
                    if final:
                        self.real_url = final
                except Exception:
                    pass
                ct = r.headers.get("Content-Type") or ""
                if ct:
                    self.content_type = ct.split(";")[0].strip() or self.content_type

                if r.status_code == 206:
                    cr = r.headers.get("Content-Range", "")
                    parsed = _parse_content_range(cr)
                    if parsed:
                        _, _, total = parsed
                        self.total_length = total
                    else:
                        # Fallback to Content-Length; may be 1 for this response.
                        try:
                            cl = int(r.headers.get("Content-Length", "0"))
                            self.total_length = max(self.total_length or 0, cl)
                        except Exception:
                            pass
                    self.range_supported = True
                elif r.status_code == 200:
                    self.range_supported = False
                    try:
                        cl = int(r.headers.get("Content-Length", "0"))
                        if cl > 0:
                            self.total_length = cl
                    except Exception:
                        pass
                else:
                    # Some servers respond 416, 403, etc.
                    self.range_supported = False
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        finally:
            self._probe_done.set()
            try:
                session.close()
            except Exception:
                pass

    def _fetch_range(self, start: int, end: int, check_abort=None) -> bool:
        # Fetch start-end inclusive from origin and store as a chunk file.
        # NOTE: we do not hold self.lock during network IO to avoid blocking seeks.
        self.probe()
        if self.range_supported is False:
            return False

        target_url = self.real_url or self.url

        # Fast path: already cached
        try:
            with self.lock:
                # self._prune_bad_segments()  <-- REMOVED aggressive check
                have = _merge_segments(self.segments)
            for s, e in have:
                if s <= start and end <= e:
                    return True
        except Exception:
            pass

        hdrs = HEADERS.copy()
        hdrs.pop("Accept", None)
        hdrs.update(self.headers or {})
        hdrs.setdefault("User-Agent", _DEFAULT_UA)
        hdrs.setdefault("Accept", "*/*")
        hdrs.setdefault("Accept-Encoding", "identity")
        hdrs["Range"] = f"bytes={start}-{end}"

        session = self._make_session()
        try:
            try:
                r = session.get(target_url, headers=hdrs, stream=True, timeout=(10, 60), allow_redirects=True)
            except Exception as e:
                self._warn("RangeCacheProxy fetch failed: %s", e)
                return False

            try:
                if r.status_code == 200:
                    # Full-body 200 - treat as no range support.
                    self.range_supported = False
                    return False
                if r.status_code != 206:
                    return False

                # Try to determine actual served range (important if origin clamps end).
                served_start, served_end = start, end
                cr = r.headers.get("Content-Range", "")
                parsed = _parse_content_range(cr)
                if parsed:
                    served_start, served_end, total = parsed
                    if total is not None:
                        self.total_length = total

                expected_len = (served_end - served_start) + 1
                if expected_len <= 0:
                    return False

                # Use a unique temporary path
                tmp_path = os.path.join(self._dir, f"tmp_fetch_{time.time()}_{threading.get_ident()}_{served_start}.part")
                bytes_written = 0
                aborted = False
                try:
                    with open(tmp_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            # Check abort signal (e.g. background download stopped or cursor moved far away)
                            if check_abort and check_abort():
                                aborted = True
                                break
                            f.write(chunk)
                            bytes_written += len(chunk)
                            if bytes_written >= expected_len:
                                break
                except Exception:
                    # IO Error during write
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    return False

                if aborted or bytes_written != expected_len:
                    # Partial/Aborted download: save what we got!
                    # Only save if we got a meaningful amount (e.g. > 4KB) to avoid cache fragmentation.
                    if bytes_written > 4096:
                        actual_end = served_start + bytes_written - 1
                        self._debug("Saving partial chunk %s-%s", served_start, actual_end)
                        self._finalize_chunk(tmp_path, served_start, actual_end)
                    else:
                        try:
                            if os.path.exists(tmp_path):
                                os.remove(tmp_path)
                        except Exception:
                            pass
                    return False

                # Full download success
                self._finalize_chunk(tmp_path, served_start, served_end)
                return True
            finally:
                try:
                    r.close()
                except Exception:
                    pass
        finally:
            session.close()

    def _read_from_cache(self, start: int, end: int) -> Tuple[int, bytes]:
        # Return (served_end, bytes). Assumes the requested interval is fully cached.
        # Reads from the actual chunk files on disk.
        # NOTE: self.segments must reflect real files; do NOT iterate over merged coverage.
        try:
            with self.lock:
                # self._prune_bad_segments() <-- REMOVED
                segs = list(self.segments)
        except Exception:
            segs = list(self.segments)

        needed_start = start
        out = bytearray()

        while needed_start <= end:
            # Choose the cached chunk that covers needed_start and extends farthest.
            best = None
            for s, e in segs:
                if s <= needed_start <= e:
                    if best is None or e > best[1]:
                        best = (s, e)
            if best is None:
                raise IOError("Cache miss while reading")

            s, e = best
            part_start = needed_start
            part_end = min(end, e)
            expected = (part_end - part_start) + 1

            try:
                with open(self._chunk_path(s, e), "rb") as f:
                    try:
                        f.seek(part_start - s)
                    except Exception:
                        raise IOError("Cache seek failed")
                    data = f.read(expected)
            except FileNotFoundError:
                # Lazy detection of missing files
                self._remove_segment(s, e)
                raise IOError("Cache miss while reading (file gone)")
            except Exception as ex:
                raise IOError(f"Cache read failed: {ex}") from ex

            if len(data) != expected:
                self._remove_segment(s, e)
                raise IOError("Cache miss while reading (truncated)")

            out.extend(data)
            needed_start = part_end + 1

        served_end = needed_start - 1
        if served_end < start:
            raise IOError("Cache miss while reading")
        return served_end, bytes(out)
    
    def _next_segment_start_after(self, offset: int) -> Optional[int]:
        try:
            off = int(offset)
        except Exception:
            return None
        nxt = None
        try:
            with self.lock:
                # self._prune_bad_segments() <-- REMOVED
                for s, _e in (self.segments or []):
                    try:
                        s = int(s)
                    except Exception:
                        continue
                    if s > off and (nxt is None or s < nxt):
                        nxt = s
        except Exception:
            return None
        return nxt

    def _find_best_segment_covering(self, offset: int) -> Optional[Tuple[int, int]]:
        try:
            off = int(offset)
        except Exception:
            return None
        best = None
        try:
            with self.lock:
                # self._prune_bad_segments() <-- REMOVED
                segs = list(self.segments or [])
        except Exception:
            segs = list(getattr(self, "segments", []) or [])
        for s, e in segs:
            try:
                s = int(s)
                e = int(e)
            except Exception:
                continue
            if s <= off <= e:
                if best is None or e > best[1]:
                    best = (s, e)
        return best

    def stream_cached_range_to(self, start: int, end: int, wfile, chunk_size: int = 512 * 1024) -> int:
        """Stream cached bytes [start..end] inclusive to wfile.

        Returns the last byte offset successfully written.
        Raises on cache miss or IO errors.
        """
        try:
            cur = int(start)
            end_i = int(end)
        except Exception:
            raise IOError("Invalid start/end")
        if end_i < cur:
            return cur - 1

        written = 0
        while cur <= end_i:
            seg = self._find_best_segment_covering(cur)
            if not seg:
                raise IOError("Cache miss while streaming")
            s, e = seg
            part_end = min(e, end_i)
            self._debug("CACHE HIT %s-%s", cur, part_end)
            path = self._chunk_path(s, e)
            try:
                with open(path, "rb") as f:
                    try:
                        f.seek(cur - s)
                    except Exception:
                        raise IOError("Cache seek failed")
                    remaining = (part_end - cur) + 1
                    while remaining > 0:
                        to_read = min(int(chunk_size), int(remaining))
                        data = f.read(to_read)
                        if not data:
                            raise IOError("Cache read failed")
                        wfile.write(data)
                        written += len(data)
                        remaining -= len(data)
            except FileNotFoundError:
                self._remove_segment(s, e)
                raise IOError("Cache file missing")
            except Exception:
                raise IOError("Cache read error")
                
            cur = part_end + 1

        return int(start) + written - 1

    def stream_origin_range_to_and_cache(self, start: int, end: int, wfile, flush_first: bool = True) -> int:
        """Stream bytes [start..end] from origin to wfile while caching them.

        Returns the last byte offset successfully written, or start-1 on failure.
        """
        try:
            req_start = int(start)
            req_end = int(end)
        except Exception:
            return int(start) - 1
        if req_end < req_start:
            return req_start - 1

        # Ensure we know if the origin supports ranges.
        try:
            self.probe()
        except Exception:
            pass
        if self.range_supported is False:
            return req_start - 1

        target_url = self.real_url or self.url

        hdrs = HEADERS.copy()
        hdrs.pop("Accept", None)
        hdrs.update(self.headers or {})
        hdrs.setdefault("User-Agent", _DEFAULT_UA)
        hdrs.setdefault("Accept", "*/*")
        hdrs.setdefault("Accept-Encoding", "identity")
        hdrs["Range"] = f"bytes={req_start}-{req_end}"

        session = self._make_session()
        try:
            try:
                r = session.get(target_url, headers=hdrs, stream=True, timeout=(10, 60), allow_redirects=True)
            except Exception as e:
                self._warn("RangeCacheProxy origin stream failed: %s", e)
                return req_start - 1

            tmp_path = None
            final_path = None
            bytes_written = 0

            try:
                if r.status_code == 200:
                    # Full-body 200: treat as no range support.
                    self.range_supported = False
                    return req_start - 1
                if r.status_code != 206:
                    return req_start - 1

                served_start = req_start
                served_end = req_end
                skip_bytes = 0

                cr = r.headers.get("Content-Range", "")
                parsed = _parse_content_range(cr)
                if parsed:
                    a, b, total = parsed
                    try:
                        if total is not None:
                            self.total_length = int(total)
                    except Exception:
                        pass
                    if a > req_start or b < req_start:
                        return req_start - 1
                    if a < req_start:
                        skip_bytes = int(req_start - a)
                    served_end = min(int(b), req_end)

                expected_len = (served_end - served_start) + 1
                if expected_len <= 0:
                    return req_start - 1

                # Use a unique temporary path to avoid race conditions between concurrent requests for the same range.
                final_path = self._chunk_path(served_start, served_end)
                tmp_path = os.path.join(self._dir, f"tmp_{time.time()}_{threading.get_ident()}_{served_start}.part")

                first = True
                remaining_skip = int(skip_bytes)
                try:
                    with open(tmp_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 1024):
                            if not chunk:
                                continue
                            if remaining_skip > 0:
                                if len(chunk) <= remaining_skip:
                                    remaining_skip -= len(chunk)
                                    continue
                                chunk = chunk[remaining_skip:]
                                remaining_skip = 0
                            if bytes_written + len(chunk) > expected_len:
                                chunk = chunk[: max(0, expected_len - bytes_written)]
                            if not chunk:
                                break

                            # Write to cache first (so if the client is slow, the disk still stays warm).
                            f.write(chunk)

                            try:
                                wfile.write(chunk)
                                if flush_first and first:
                                    try:
                                        wfile.flush()
                                    except Exception:
                                        pass
                                    first = False
                            except Exception:
                                # Client disconnected; SAVE PARTIAL CACHE
                                if bytes_written > 0:
                                    actual_end = served_start + bytes_written - 1
                                    self._debug("Saving partial stream chunk %s-%s", served_start, actual_end)
                                    f.close() # Ensure file is closed before finalizing
                                    self._finalize_chunk(tmp_path, served_start, actual_end)
                                    return actual_end
                                else:
                                    f.close()
                                    try:
                                        os.remove(tmp_path)
                                    except Exception:
                                        pass
                                    return req_start - 1

                            bytes_written += len(chunk)
                            if bytes_written >= expected_len:
                                break
                except Exception as e:
                    self._debug("Error writing to temp file: %s", e)
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except Exception:
                        pass
                    return req_start - 1

                if bytes_written != expected_len:
                    # Interrupted / truncated fetch from origin. SAVE PARTIAL CACHE.
                    if bytes_written > 0:
                        actual_end = served_start + bytes_written - 1
                        self._debug("Saving truncated stream chunk %s-%s", served_start, actual_end)
                        self._finalize_chunk(tmp_path, served_start, actual_end)
                        return actual_end
                    else:
                        try:
                            os.remove(tmp_path)
                        except Exception:
                            pass
                        return (served_start + bytes_written - 1) if bytes_written > 0 else (req_start - 1)

                # Success: save full chunk
                self._finalize_chunk(tmp_path, served_start, served_end)
                return served_end
            finally:
                try:
                    r.close()
                except Exception:
                    pass
                # Cleanup partial temp file if needed (e.g. if we returned early without finalizing)
                try:
                    if tmp_path and os.path.exists(tmp_path):
                        # Check if we already finalized it (moved it) - difficult since filename changes.
                        # Rely on _finalize_chunk renaming it. If it's still here, it's trash.
                        # BUT wait, _finalize_chunk moves it. So if it exists here, it wasn't finalized.
                        os.remove(tmp_path)
                except Exception:
                    pass
        finally:
            session.close()

    def _advance_bg_cursor_locked(self) -> None:
        """Advance bg_cursor to the first byte offset not already covered by cached segments.

        Assumes self.lock is held.
        """
        try:
            cur = int(self.bg_cursor)
        except Exception:
            cur = 0
        if cur < 0:
            cur = 0
        have = _merge_segments(self.segments)
        # Walk contiguous coverage starting at cur.
        advanced = True
        while advanced:
            advanced = False
            for s, e in have:
                if s <= cur <= e:
                    cur = e + 1
                    advanced = True
                    break
                if s > cur:
                    break
        self.bg_cursor = cur

    def maybe_start_background_download(self) -> None:
        if not self.background_download:
            return
        if self._bg_thread and self._bg_thread.is_alive():
            return
        self._bg_stop.clear()

        def run() -> None:
            try:
                self._debug("BG download starting")
                self.probe()
                if self.range_supported is False:
                    self._debug("BG download aborted (no range support)")
                    return

                # Bootstrap size: make sure the start of the file is cached deeply.
                bootstrap_bytes = max(int(self.initial_burst_bytes), int(self.background_chunk_bytes))
                jump_threshold = max(int(self.background_chunk_bytes), 4 * 1024 * 1024)

                first = True
                while not self._bg_stop.is_set():
                    # Stop if idle for a while.
                    if time.time() - self.last_access > 120:
                        self._debug("BG download stopping (idle)")
                        return

                    ms = None
                    me = None

                    with self.lock:
                        # self._prune_bad_segments() <-- REMOVED

                        # After the initial bootstrap has been cached, follow large forward seeks.
                        if self.bootstrap_done:
                            try:
                                req = int(self.last_req_start)
                            except Exception:
                                req = 0
                            if abs(req - int(self.bg_cursor)) > jump_threshold:
                                self._debug("BG download jump %s -> %s", self.bg_cursor, req)
                                self.bg_cursor = req

                        # Always download from the first not-yet-cached byte at/after bg_cursor.
                        self._advance_bg_cursor_locked()
                        start = max(0, int(self.bg_cursor))

                        if self.total_length is not None and start >= self.total_length:
                            # Finished downloading? Sleep longer.
                            time.sleep(1.0)
                            continue

                        chunk_target = bootstrap_bytes if first else int(self.background_chunk_bytes)
                        end = start + int(chunk_target) - 1
                        if self.total_length is not None:
                            end = min(end, self.total_length - 1)

                        miss = _missing_segments(self.segments, start, end)
                        if miss:
                            ms, me = miss[0]
                        else:
                            # Already cached in this window; jump cursor past it.
                            self.bg_cursor = end + 1

                    if ms is None or me is None:
                        # No work needed, sleep longer to reduce CPU
                        time.sleep(0.5)
                        continue

                    # Snapshot the user's position at the start of this chunk download.
                    # We use this to detect if the user seeks away *during* the download.
                    try:
                        ref_req = int(self.last_req_start)
                    except Exception:
                        ref_req = 0

                    def check_should_abort():
                        if self._bg_stop.is_set():
                            return True
                        # If user seeks away far from where they were when we started this chunk, stop.
                        try:
                            cur_req = int(self.last_req_start)
                            # If cursor moved > 2MB from the reference point, assume a seek occurred.
                            # Normal playback (audio) moves much slower than this.
                            if abs(cur_req - ref_req) > 2 * 1024 * 1024:
                                self._debug("BG aborting chunk (seek detected: %s -> %s)", ref_req, cur_req)
                                return True
                        except Exception:
                            pass
                        return False

                    self._debug("BG fetching %s-%s", ms, me)
                    ok = self._fetch_range(ms, me, check_abort=check_should_abort)
                    if not ok:
                        time.sleep(1.0)
                        continue

                    if first:
                        first = False

                    # Mark bootstrap done once we have contiguous coverage beyond initial_burst_bytes.
                    with self.lock:
                        try:
                            # self._prune_bad_segments() <-- REMOVED
                            self._advance_bg_cursor_locked()
                            if (not self.bootstrap_done) and int(self.bg_cursor) >= int(self.initial_burst_bytes):
                                self.bootstrap_done = True
                        except Exception:
                            pass

                    # Small pause to avoid pegging CPU
                    time.sleep(0.1)
            except Exception as e:
                LOG.debug("Background download stopped: %s", e)

        self._bg_thread = threading.Thread(target=run, name="RangeCacheProxyBG", daemon=True)
        self._bg_thread.start()

    def stop(self) -> None:
        with self._lock:
            if self._server is None:
                return
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._thread = None
            self._port = None
            self._ready.clear()

    def _wait_ready(self, timeout: float = 2.0) -> bool:
        import http.client
        deadline = time.time() + max(0.1, float(timeout))
        while time.time() < deadline:
            with self._lock:
                if self._port is None:
                    time.sleep(0.05)
                    continue
                port = self._port
            try:
                conn = http.client.HTTPConnection(self._host, port, timeout=0.5)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                try:
                    _ = resp.read()
                except Exception:
                    pass
                ok = (resp.status == 200)
                try:
                    conn.close()
                except Exception:
                    pass
                if ok:
                    self._ready.set()
                    return True
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
            time.sleep(0.05)
        return False

    def is_ready(self) -> bool:
        # Active health check (the server may have died while the event is still set).
        # Do not clear the readiness event on a single failure; transient hiccups
        # should not trigger restarts that break in-flight VLC connections.
        try:
            return bool(self._wait_ready(timeout=0.25))
        except Exception:
            return False

    @property
    def base_url(self) -> str:
        self.start()
        try:
            self._ready.wait(timeout=2.0)
        except Exception:
            pass
        with self._lock:
            if self._port is None:
                raise RuntimeError("RangeCacheProxy not started")
            return f"http://{self._host}:{self._port}"

    def proxify(self, url: str, headers: Optional[Dict[str, str]] = None, skip_redirect_resolve: bool = False) -> str:
        """
        Register a URL and return a local proxy URL.

        The id is a short stable hash of (url + headers subset). Using a stable id
        allows VLC retries without re-registering, while keeping cache per URL.
        """
        if not url:
            return url
        self.start()

        # Include headers in id because some hosts require specific Referer/User-Agent
        # to permit range access.
        h = headers or {}
        id_src = url + "\n" + "\n".join(f"{k.lower()}:{v}" for k, v in sorted(h.items(), key=lambda kv: kv[0].lower()))
        sid = _sha256_hex(id_src)[:24]

        # Persist the mapping so /media can still resolve even if the in-memory entry is missing.
        self._save_mapping(sid, url, headers)

        ent = self._get_or_create_entry(sid, url, headers)
        
        # If the caller says redirects are already resolved, set real_url to skip that step in probe()
        if skip_redirect_resolve:
            ent.real_url = url
        
        # Launch probe in a background thread so proxify() returns immediately.
        # The HTTP handler will wait for the probe if needed when VLC requests bytes.
        def _bg_probe():
            try:
                # Never hold ent.lock (segment/cache lock) while probing the origin.
                # A slow probe would otherwise block /media reads and delay playback.
                ent.probe()
            except Exception:
                pass
        try:
            threading.Thread(target=_bg_probe, daemon=True).start()
        except Exception:
            pass

        return f"{self.base_url}/media?id={sid}"

    def prune(self, max_entries: int = 20, max_idle_seconds: int = 1800) -> None:
        # Optional: drop very old entries from memory.
        now = time.time()
        with self._lock:
            items = list(self._entries.items())
            items.sort(key=lambda kv: kv[1].last_access)
            # Remove idle
            for sid, ent in items:
                if len(self._entries) <= max_entries:
                    break
                if now - ent.last_access < max_idle_seconds:
                    continue
                try:
                    ent.stop_background()
                except Exception:
                    pass
                self._entries.pop(sid, None)


class RangeCacheProxy:
    def __init__(
        self,
        cache_dir: Optional[str] = None,
        prefetch_kb: int = 16384,
        background_download: bool = True,
        background_chunk_kb: int = 8192,
        inline_window_kb: int = 1024,
        initial_burst_kb: int = 32768,
        initial_inline_prefetch_kb: int = 1024,
        debug_logs: bool = False,
    ):
        base = cache_dir or os.path.join(tempfile.gettempdir(), "BlindRSS_streamcache")
        _safe_mkdir(base)
        self.cache_dir = base
        self.prefetch_bytes = max(512 * 1024, int(prefetch_kb) * 1024)
        # For low-latency seeking: never block a single VLC request on huge prefetch.
        # We may still download ahead in the background.
        self.inline_window_bytes = max(256 * 1024, int(inline_window_kb) * 1024)
        # Burst prefetch: fetch a larger first background range so early seeks don't stall.
        # Minimum 4 MB to ensure reasonable caching, but don't force huge downloads that delay playback.
        self.initial_burst_bytes = max(4 * 1024 * 1024, int(initial_burst_kb) * 1024)
        # Inline prefetch: small cushion added to early seeks/ranged reads to reduce immediate rebuffering.
        try:
            self.initial_inline_prefetch_bytes = max(0, min(_INLINE_PREFETCH_CAP_BYTES, int(initial_inline_prefetch_kb) * 1024))
        except Exception:
            self.initial_inline_prefetch_bytes = min(_INLINE_PREFETCH_CAP_BYTES, 1024 * 1024)
        self.max_inline_prefetch_bytes = 2 * 1024 * 1024
        self.background_download = bool(background_download)
        self.background_chunk_bytes = max(1024 * 1024, int(background_chunk_kb) * 1024)
        self.debug_logs = bool(debug_logs)

        self._entries: Dict[str, _Entry] = {}
        self._lock = threading.RLock()

        self._server: Optional[_ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._host = "127.0.0.1"
        self._port: Optional[int] = None
        # Once a port is chosen, try to reuse it on restarts so existing MRLs don't break.
        self._preferred_port: Optional[int] = None
        self._ready = threading.Event()

        self._map_dir = os.path.join(self.cache_dir, "mappings")
        _safe_mkdir(self._map_dir)

    def _debug(self, fmt: str, *args) -> None:
        if not bool(getattr(self, "debug_logs", False)):
            return
        try:
            LOG.info("PROXY_DEBUG: " + fmt, *args)
        except Exception:
            pass

    def _warn(self, fmt: str, *args) -> None:
        try:
            LOG.warning("PROXY_WARNING: " + fmt, *args)
        except Exception:
            pass

    def _mapping_path(self, sid: str) -> str:
        return os.path.join(self._map_dir, f"{sid}.json")

    def _save_mapping(self, sid: str, url: str, headers: Optional[Dict[str, str]]) -> None:
        try:
            _safe_mkdir(self._map_dir)
            tmp = self._mapping_path(sid) + ".tmp"
            payload = {"url": url, "headers": headers or {}}
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f)
            os.replace(tmp, self._mapping_path(sid))
        except Exception:
            pass

    def _load_mapping(self, sid: str) -> Optional[Dict[str, object]]:
        try:
            path = self._mapping_path(sid)
            if not os.path.exists(path):
                return None
            with open(path, "r", encoding="utf-8") as f:
                obj = json.load(f)
            if not isinstance(obj, dict):
                return None
            url = obj.get("url")
            if not isinstance(url, str) or not url:
                return None
            headers = obj.get("headers")
            if not isinstance(headers, dict):
                headers = {}
            # Force keys/values to strings
            safe_headers: Dict[str, str] = {}
            for k, v in headers.items():
                try:
                    safe_headers[str(k)] = str(v)
                except Exception:
                    continue
            return {"url": url, "headers": safe_headers}
        except Exception:
            return None

    def _get_or_create_entry(self, sid: str, url: str, headers: Optional[Dict[str, str]]) -> _Entry:
        with self._lock:
            ent = self._entries.get(sid)
            if ent is not None:
                return ent
            ent = _Entry(
                url=url,
                headers=headers or {},
                cache_dir=self.cache_dir,
                prefetch_bytes=self.prefetch_bytes,
                background_download=self.background_download,
                initial_burst_bytes=self.initial_burst_bytes,
                initial_inline_prefetch_bytes=getattr(self, 'initial_inline_prefetch_bytes', 0),
                background_chunk_bytes=self.background_chunk_bytes,
                debug_logs=bool(getattr(self, "debug_logs", False)),
            )
            self._entries[sid] = ent
            return ent

    def start(self) -> None:
        """Start the local HTTP server.

        Important: never restart an *alive* server from here.

        VLC streams can stay connected for a long time to a single
        http://127.0.0.1:<port>/media?id=... URL. If we stop/rebind the server
        while VLC is still using that URL, VLC will log:
            "cannot connect to 127.0.0.1:<port>"

        So we only restart if the server thread is actually dead.
        """

        # Fast path: server already running.
        with self._lock:
            if self._server is not None and self._thread is not None and self._thread.is_alive():
                # Best-effort readiness check (do not restart on failure).
                pass

        if self._server is not None and self._thread is not None and self._thread.is_alive():
            try:
                self._wait_ready(timeout=1.0)
            except Exception:
                pass
            return

        # If the server exists but the thread is dead, ensure it's fully stopped.
        with self._lock:
            if self._server is not None:
                try:
                    self.stop()
                except Exception:
                    pass

        with self._lock:
            self._ready.clear()
            proxy = self

            class Handler(BaseHTTPRequestHandler):
                protocol_version = "HTTP/1.1"

                def log_message(self, fmt: str, *args) -> None:
                    # silence
                    try:
                        LOG.debug("RangeCacheProxy: " + fmt, *args)
                    except Exception:
                        pass

                def handle_one_request(self) -> None:
                    # VLC/clients frequently abort the local HTTP connection while seeking/stopping.
                    # Swallow these common disconnects to avoid noisy tracebacks.
                    try:
                        return super().handle_one_request()
                    except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
                        return
                    except OSError as e:
                        if getattr(e, "winerror", None) in (10053, 10054):
                            return
                        raise

                def _send_health(self) -> None:
                    body = b"ok"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    try:
                        self.wfile.write(body)
                    except Exception:
                        pass

                def do_HEAD(self) -> None:
                    parsed = urlparse(self.path)
                    if parsed.path == "/health":
                        proxy._ready.set()
                        self._send_health()
                        return
                    if parsed.path != "/media":
                        self.send_error(404, "Not Found")
                        return
                    q = parse_qs(parsed.query)
                    sid = q.get("id", [None])[0]
                    if not sid:
                        self.send_error(404, "Not Found")
                        return
                    with proxy._lock:
                        ent = proxy._entries.get(sid)
                    if not ent:
                        info = proxy._load_mapping(sid)
                        if info is not None:
                            ent = proxy._get_or_create_entry(sid, str(info["url"]), dict(info.get("headers") or {}))
                    if not ent:
                        self.send_error(404, "Not Found")
                        return
                    try:
                        ent.touch()
                    except Exception:
                        pass
                    # VLC uses early HEAD responses to decide whether an HTTP
                    # source is seekable. proxify() already starts the probe in
                    # the background, so wait briefly for it and include length
                    # metadata when available without doing network I/O here.
                    try:
                        if not ent._probe_done.is_set():
                            ent._probe_done.wait(timeout=_PROBE_WAIT_S)
                    except Exception:
                        pass
                    self.send_response(200)
                    self.send_header("Content-Type", ent.content_type)
                    if ent.total_length is not None:
                        self.send_header("Content-Length", str(ent.total_length))
                    # Always advertise byte ranges for VLC.
                    self.send_header("Accept-Ranges", "bytes")
                    self.end_headers()

                def do_GET(self) -> None:
                    parsed = urlparse(self.path)
                    if parsed.path == "/health":
                        proxy._ready.set()
                        self._send_health()
                        return
                    if parsed.path != "/media":
                        self.send_error(404, "Not Found")
                        return

                    q = parse_qs(parsed.query)
                    sid = q.get("id", [None])[0]
                    if not sid:
                        self.send_error(404, "Not Found")
                        return

                    with proxy._lock:
                        ent = proxy._entries.get(sid)
                    if not ent:
                        info = proxy._load_mapping(sid)
                        if info is not None:
                            ent = proxy._get_or_create_entry(sid, str(info["url"]), dict(info.get("headers") or {}))
                    if not ent:
                        self.send_error(404, "Not Found")
                        return

                    try:
                        ent.touch()
                    except Exception:
                        pass

                    # Wait briefly for the background probe to complete.
                    # Keep this short so slow trackers don't block playback startup.
                    try:
                        ent._probe_done.wait(timeout=_PROBE_WAIT_S)
                    except Exception:
                        pass

                    range_hdr = (self.headers.get("Range") or "").strip()
                    proxy._debug("GET /media id=%s Range=%s", sid, range_hdr)

                    # If origin does not support range, just stream through (no caching).
                    if ent.range_supported is False:
                        proxy._debug("Range not supported, streaming directly.")
                        hdrs = HEADERS.copy()
                        hdrs.pop("Accept", None)
                        hdrs.update(ent.headers or {})
                        hdrs.setdefault("User-Agent", _DEFAULT_UA)
                        hdrs.setdefault("Accept", "*/*")
                        hdrs.setdefault("Accept-Encoding", "identity")

                        # Preserve the caller's Range header if present; some servers ignore it.
                        rh = self.headers.get("Range")
                        if rh:
                            hdrs["Range"] = rh

                        session = ent._make_session()
                        try:
                            try:
                                r = session.get(ent.url, headers=hdrs, stream=True, timeout=(10, 60), allow_redirects=True)
                            except Exception as e:
                                proxy._debug("Origin fetch failed: %s", e)
                                self.send_error(502, f"Origin fetch failed: {e}")
                                return
                            try:
                                self.send_response(r.status_code)
                                for k, v in r.headers.items():
                                    lk = k.lower()
                                    if lk in ("transfer-encoding", "connection", "keep-alive", "proxy-authenticate",
                                              "proxy-authorization", "te", "trailers", "upgrade"):
                                        continue
                                    self.send_header(k, v)
                                self.end_headers()
                                for chunk in r.iter_content(chunk_size=256 * 1024):
                                    if not chunk:
                                        continue
                                    try:
                                        self.wfile.write(chunk)
                                    except Exception:
                                        break
                                return
                            finally:
                                try:
                                    r.close()
                                except Exception:
                                    pass
                        finally:
                            try:
                                session.close()
                            except Exception:
                                pass

                    is_range_req = bool(range_hdr)
                    start = 0
                    end = None

                    if is_range_req:
                        start_end = _parse_range_header(range_hdr, ent.total_length)
                        if not start_end:
                            # Invalid/unsupported range
                            if ent.total_length is not None:
                                self.send_response(416)
                                self.send_header("Content-Range", f"bytes */{ent.total_length}")
                                self.end_headers()
                            else:
                                self.send_error(416, "Requested Range Not Satisfiable")
                            return
                        start, end = start_end
                    else:
                        start = 0
                        end = (ent.total_length - 1) if ent.total_length is not None else None

                    # Clamp/validate against known length.
                    # IMPORTANT: For open-ended requests (bytes=X-), limit response to inline_window_bytes
                    # to prevent blocking on huge file transfers. VLC will request more as needed.
                    open_ended = (end is None)
                    if ent.total_length is not None:
                        if start < 0:
                            start = 0
                        if start >= ent.total_length:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{ent.total_length}")
                            self.end_headers()
                            return
                        if end is None:
                            # Limit open-ended requests to inline window to keep playback responsive
                            end = min(start + max(0, int(proxy.inline_window_bytes) - 1), ent.total_length - 1)
                        else:
                            end = min(int(end), ent.total_length - 1)
                    else:
                        # Unknown total length. Do not attempt an unbounded stream.
                        if end is None:
                            end = start + max(0, int(proxy.inline_window_bytes) - 1)

                    # Track the most recent requested offset (helps background downloader follow seeks).
                    try:
                        ent.last_req_start = int(start)
                        ent.last_req_time = time.time()
                    except Exception:
                        pass

                    if end < start:
                        if ent.total_length is not None:
                            self.send_response(416)
                            self.send_header("Content-Range", f"bytes */{ent.total_length}")
                            self.end_headers()
                        else:
                            self.send_error(416, "Requested Range Not Satisfiable")
                        return

                    # Respond headers.
                    if is_range_req:
                        length = (end - start) + 1
                        self.send_response(206)
                        self.send_header("Content-Type", ent.content_type)
                        self.send_header("Accept-Ranges", "bytes")
                        self.send_header("Content-Length", str(length))
                        if ent.total_length is not None:
                            self.send_header("Content-Range", f"bytes {start}-{end}/{ent.total_length}")
                        else:
                            self.send_header("Content-Range", f"bytes {start}-{end}/*")
                        self.end_headers()
                        proxy._debug("206 Partial Content %s-%s/%s", start, end, ent.total_length)
                    else:
                        self.send_response(200)
                        self.send_header("Content-Type", ent.content_type)
                        if ent.total_length is not None:
                            self.send_header("Content-Length", str(ent.total_length))
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        proxy._debug("200 OK (Full Content)")

                    # Start background downloader early so the beginning of the file is cached ASAP.
                    try:
                        ent.maybe_start_background_download()
                    except Exception:
                        pass

                                        # Stream response using cache when possible; otherwise stream from origin while caching.
                    cur = start
                    first_flush = True

                    while cur <= end:
                        # Serve from cache if possible.
                        seg = None
                        try:
                            seg = ent._find_best_segment_covering(cur)
                        except Exception:
                            seg = None

                        if seg:
                            s, e = seg
                            part_end = min(e, end)
                            try:
                                ent.stream_cached_range_to(cur, part_end, self.wfile)
                                if first_flush:
                                    try:
                                        self.wfile.flush()
                                    except Exception:
                                        pass
                                    first_flush = False
                                cur = part_end + 1
                                continue
                            except Exception:
                                # Cache read failed (file missing / partial). Reload metadata and fall back to origin.
                                try:
                                    ent._load_existing_segments()
                                except Exception:
                                    pass

                        # Cache miss: stream from origin for this gap, and cache it.
                        try:
                            nxt = ent._next_segment_start_after(cur)
                        except Exception:
                            nxt = None
                        if nxt is None or int(nxt) <= int(cur):
                            miss_end = end
                        else:
                            miss_end = min(end, int(nxt) - 1)

                        proxy._debug("Cache miss at %s, fetching %s-%s", cur, cur, miss_end)
                        try:
                            streamed_end = ent.stream_origin_range_to_and_cache(cur, miss_end, self.wfile, flush_first=first_flush)
                        except Exception:
                            streamed_end = cur - 1

                        if streamed_end < cur:
                            break

                        if first_flush:
                            try:
                                self.wfile.flush()
                            except Exception:
                                pass
                            first_flush = False

                        cur = streamed_end + 1
# Bind and start. Prefer reusing the same port across restarts.
            bound = False
            if self._preferred_port is not None:
                try:
                    self._server = _ThreadingHTTPServer((self._host, int(self._preferred_port)), Handler)
                    bound = True
                except Exception:
                    self._server = None
                    bound = False
            if not bound:
                self._server = _ThreadingHTTPServer((self._host, 0), Handler)
            self._port = self._server.server_address[1]
            if self._preferred_port is None:
                self._preferred_port = self._port

            def run() -> None:
                try:
                    self._server.serve_forever(poll_interval=0.25)
                except Exception as e:
                    self._warn("RangeCacheProxy server error: %s", e)
                finally:
                    # Mark as not ready if the server stops unexpectedly.
                    try:
                        self._ready.clear()
                    except Exception:
                        pass

            self._thread = threading.Thread(target=run, name="RangeCacheProxy", daemon=True)
            self._thread.start()

        # Wait until responding
        self._wait_ready(timeout=2.0)

    def stop(self) -> None:
        with self._lock:
            if self._server is None:
                return
            try:
                self._server.shutdown()
            except Exception:
                pass
            try:
                self._server.server_close()
            except Exception:
                pass
            self._server = None
            self._thread = None
            self._port = None
            self._ready.clear()

    def _wait_ready(self, timeout: float = 2.0) -> bool:
        import http.client
        deadline = time.time() + max(0.1, float(timeout))
        while time.time() < deadline:
            with self._lock:
                if self._port is None:
                    time.sleep(0.05)
                    continue
                port = self._port
            try:
                conn = http.client.HTTPConnection(self._host, port, timeout=0.5)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                try:
                    _ = resp.read()
                except Exception:
                    pass
                ok = (resp.status == 200)
                try:
                    conn.close()
                except Exception:
                    pass
                if ok:
                    self._ready.set()
                    return True
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
            time.sleep(0.05)
        return False

    def is_ready(self) -> bool:
        # Active health check (the server may have died while the event is still set).
        # Do not clear the readiness event on a single failure; transient hiccups
        # should not trigger restarts that break in-flight VLC connections.
        try:
            return bool(self._wait_ready(timeout=0.25))
        except Exception:
            return False

    @property
    def base_url(self) -> str:
        self.start()
        try:
            self._ready.wait(timeout=2.0)
        except Exception:
            pass
        with self._lock:
            if self._port is None:
                raise RuntimeError("RangeCacheProxy not started")
            return f"http://{self._host}:{self._port}"

    def proxify(self, url: str, headers: Optional[Dict[str, str]] = None, skip_redirect_resolve: bool = False) -> str:
        """
        Register a URL and return a local proxy URL.

        The id is a short stable hash of (url + headers subset). Using a stable id
        allows VLC retries without re-registering, while keeping cache per URL.
        """
        if not url:
            return url
        self.start()

        # Include headers in id because some hosts require specific Referer/User-Agent
        # to permit range access.
        h = headers or {}
        id_src = url + "\n" + "\n".join(f"{k.lower()}:{v}" for k, v in sorted(h.items(), key=lambda kv: kv[0].lower()))
        sid = _sha256_hex(id_src)[:24]

        # Persist the mapping so /media can still resolve even if the in-memory entry is missing.
        self._save_mapping(sid, url, headers)

        ent = self._get_or_create_entry(sid, url, headers)
        
        # If the caller says redirects are already resolved, set real_url to skip that step in probe()
        if skip_redirect_resolve:
            ent.real_url = url
        
        # Launch probe in a background thread so proxify() returns immediately.
        # The HTTP handler will wait for the probe if needed when VLC requests bytes.
        def _bg_probe():
            try:
                # Never hold ent.lock (segment/cache lock) while probing the origin.
                # A slow probe would otherwise block /media reads and delay playback.
                ent.probe()
            except Exception:
                pass
        try:
            threading.Thread(target=_bg_probe, daemon=True).start()
        except Exception:
            pass

        return f"{self.base_url}/media?id={sid}"

    def prune(self, max_entries: int = 20, max_idle_seconds: int = 1800) -> None:
        # Optional: drop very old entries from memory.
        now = time.time()
        with self._lock:
            items = list(self._entries.items())
            items.sort(key=lambda kv: kv[1].last_access)
            # Remove idle
            for sid, ent in items:
                if len(self._entries) <= max_entries:
                    break
                if now - ent.last_access < max_idle_seconds:
                    continue
                try:
                    ent.stop_background()
                except Exception:
                    pass
                self._entries.pop(sid, None)


_RANGE_PROXY_SINGLETON: Optional[RangeCacheProxy] = None


def get_range_cache_proxy(
    cache_dir: Optional[str] = None,
    prefetch_kb: int = 16384,
    background_download: bool = True,
    background_chunk_kb: int = 8192,
    inline_window_kb: int = 1024,
    initial_burst_kb: int = 32768,
    initial_inline_prefetch_kb: int = 1024,
    debug_logs: bool = False,
) -> RangeCacheProxy:
    global _RANGE_PROXY_SINGLETON
    if _RANGE_PROXY_SINGLETON is None:
        _RANGE_PROXY_SINGLETON = RangeCacheProxy(
            cache_dir=cache_dir,
            prefetch_kb=prefetch_kb,
            background_download=background_download,
            background_chunk_kb=background_chunk_kb,
            inline_window_kb=inline_window_kb,
            initial_burst_kb=initial_burst_kb,
            initial_inline_prefetch_kb=initial_inline_prefetch_kb,
            debug_logs=debug_logs,
        )
    else:
        # Allow tuning without replacing the server
        try:
            if cache_dir:
                _RANGE_PROXY_SINGLETON.cache_dir = cache_dir
                try:
                    _RANGE_PROXY_SINGLETON._map_dir = os.path.join(cache_dir, "mappings")
                    _safe_mkdir(_RANGE_PROXY_SINGLETON._map_dir)
                except Exception:
                    pass
            if prefetch_kb:
                _RANGE_PROXY_SINGLETON.prefetch_bytes = max(512 * 1024, int(prefetch_kb) * 1024)
            if inline_window_kb:
                _RANGE_PROXY_SINGLETON.inline_window_bytes = max(256 * 1024, int(inline_window_kb) * 1024)
            if initial_burst_kb:
                _RANGE_PROXY_SINGLETON.initial_burst_bytes = max(4 * 1024 * 1024, int(initial_burst_kb) * 1024)
            if initial_inline_prefetch_kb:
                try:
                    _RANGE_PROXY_SINGLETON.initial_inline_prefetch_bytes = max(0, min(_INLINE_PREFETCH_CAP_BYTES, int(initial_inline_prefetch_kb) * 1024))
                except Exception:
                    pass
            _RANGE_PROXY_SINGLETON.background_download = bool(background_download)
            if background_chunk_kb:
                _RANGE_PROXY_SINGLETON.background_chunk_bytes = max(1024 * 1024, int(background_chunk_kb) * 1024)
            _RANGE_PROXY_SINGLETON.debug_logs = bool(debug_logs)
            try:
                for _sid, _ent in list(_RANGE_PROXY_SINGLETON._entries.items()):
                    _ent.debug_logs = bool(debug_logs)
            except Exception:
                pass
        except Exception:
            pass
    return _RANGE_PROXY_SINGLETON
