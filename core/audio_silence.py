# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import math
import shutil
import subprocess
import time
from array import array
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

try:
    import webrtcvad
except Exception:
    webrtcvad = None


def _rms(chunk: bytes, sample_width: int, channels: int) -> float:
    """
    Calculate RMS for signed PCM samples.
    Assumes little-endian signed samples; we decode to array('h') for 16-bit audio.
    """
    if sample_width != 2:
        # Only 16-bit is used by our ffmpeg probe; fall back to best-effort magnitude.
        if not chunk:
            return 0.0
        vals = [b - 128 for b in chunk]
        sq = sum(v * v for v in vals)
        return math.sqrt(sq / len(vals))

    if not chunk:
        return 0.0
    arr = array("h")
    arr.frombytes(chunk)
    if channels > 1:
        # Collapse to mono by averaging pairs
        mono = []
        try:
            for i in range(0, len(arr), channels):
                mono.append(sum(arr[i:i + channels]) / float(channels))
        except Exception:
            mono = list(arr)
    else:
        mono = arr
    if not mono:
        return 0.0
    # Integer multiply for the mono path (the hot one): float() per sample cost
    # more than the multiply itself and the result is identical.
    sq = sum(v * v for v in mono)
    return math.sqrt(sq / len(mono))


def _dbfs(rms: float, full_scale: float = 32768.0) -> float:
    if rms <= 0:
        return -120.0
    return 20.0 * math.log10(rms / full_scale)


def merge_ranges(ranges: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    if not ranges:
        return []
    cleaned = []
    for s, e in ranges:
        try:
            s_i = int(s)
            e_i = int(e)
        except Exception:
            continue
        if e_i < s_i:
            continue
        cleaned.append((s_i, e_i))
    cleaned.sort(key=lambda p: (p[0], p[1]))
    out: List[Tuple[int, int]] = []
    cs, ce = cleaned[0]
    for s, e in cleaned[1:]:
        if s <= ce + 1:
            ce = max(ce, e)
        else:
            out.append((cs, ce))
            cs, ce = s, e
    out.append((cs, ce))
    return out


def merge_ranges_with_gap(ranges: Sequence[Tuple[int, int]], gap_ms: int) -> List[Tuple[int, int]]:
    """
    Merge overlapping/adjacent ranges, and also ranges separated by <= gap_ms.
    Helps smooth out tiny non-silent blips between long quiet stretches.
    """
    merged = merge_ranges(ranges)
    if not merged:
        return merged
    gap_ms = max(0, int(gap_ms))
    out: List[Tuple[int, int]] = []
    cs, ce = merged[0]
    for s, e in merged[1:]:
        if s <= ce + gap_ms:
            ce = max(ce, e)
        else:
            out.append((cs, ce))
            cs, ce = s, e
    out.append((cs, ce))
    return out


def _detect_vad_ranges(
    pcm_stream: Iterable[bytes],
    sample_rate: int,
    frame_ms: int,
    min_silence_ms: int,
    aggressiveness: int,
    merge_gap_ms: int,
    threshold_db: float,
    progress_callback: Optional[Callable[[List[Tuple[int, int]], int], None]] = None,
    progress_interval_ms: int = 5000,
) -> List[Tuple[int, int]]:
    """Detect silent spans in a PCM stream.

    ``progress_callback(ranges_so_far, scanned_ms)`` is called roughly every
    ``progress_interval_ms`` of scanned audio so a caller can act on early
    results instead of waiting for the whole source (see the paced scan in
    scan_audio_for_silence).
    """
    if webrtcvad is None:
        raise RuntimeError("webrtcvad not available; install the webrtcvad package")
    vad = webrtcvad.Vad(int(max(0, min(3, aggressiveness))))
    frame_ms = int(frame_ms)
    if frame_ms not in (10, 20, 30):
        frame_ms = 30
    frame_bytes = int(sample_rate * (frame_ms / 1000.0) * 2)  # mono 16-bit

    buf = b""
    offset_ms = 0
    silence_start: Optional[int] = None
    ranges: List[Tuple[int, int]] = []
    is_speech_fn = vad.is_speech
    threshold = float(threshold_db)
    last_progress_ms = 0

    for chunk in pcm_stream:
        if not chunk:
            continue
        # Slice frames out by index instead of `del buf[:frame_bytes]`: that
        # memmoved the whole remaining buffer once per 30ms frame.
        buf = buf + chunk if buf else chunk
        pos = 0
        limit = len(buf) - frame_bytes
        while pos <= limit:
            frame = buf[pos:pos + frame_bytes]
            pos += frame_bytes
            # The RMS/dBFS check only matters when the VAD already says "not
            # speech". Computing it for every frame burned ~90% of this loop on
            # a typical podcast, where ~98% of frames are speech.
            silent = (not is_speech_fn(frame, sample_rate)) and (
                _dbfs(_rms(frame, sample_width=2, channels=1)) <= threshold
            )
            if silent:
                if silence_start is None:
                    silence_start = offset_ms
            else:
                if silence_start is not None:
                    dur = offset_ms - silence_start
                    if dur >= min_silence_ms:
                        ranges.append((silence_start, offset_ms))
                    silence_start = None
            offset_ms += frame_ms
        buf = buf[pos:] if pos else buf

        if progress_callback is not None and offset_ms - last_progress_ms >= progress_interval_ms:
            last_progress_ms = offset_ms
            try:
                progress_callback(merge_ranges_with_gap(ranges, gap_ms=max(0, merge_gap_ms)), offset_ms)
            except Exception:
                pass

    if silence_start is not None:
        if (offset_ms - silence_start) >= min_silence_ms:
            ranges.append((silence_start, offset_ms))

    return merge_ranges_with_gap(ranges, gap_ms=max(0, merge_gap_ms))


class StreamingSilenceDetector:
    """
    Streaming silence detector that consumes PCM and records [start_ms, end_ms] silent spans.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        sample_width: int = 2,
        channels: int = 1,
        window_ms: int = 30,
        min_silence_ms: int = 800,
        threshold_db: float = -40.0,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.sample_width = int(sample_width)
        self.channels = int(channels)
        self.window_ms = max(10, int(window_ms))
        self.threshold_db = float(threshold_db)
        self.min_silence_windows = max(1, math.ceil(int(min_silence_ms) / self.window_ms))
        self.window_bytes = int(
            (self.sample_rate * self.window_ms * self.sample_width * self.channels) / 1000
        )

        self._buf = bytearray()
        self._current_window = 0
        self._silent_run = 0
        self._run_start_window: Optional[int] = None
        self._ranges: List[Tuple[int, int]] = []

    def feed(self, data: bytes) -> None:
        if not data:
            return
        self._buf.extend(data)
        while len(self._buf) >= self.window_bytes:
            window = self._buf[: self.window_bytes]
            del self._buf[: self.window_bytes]
            rms = _rms(window, self.sample_width, self.channels)
            db = _dbfs(rms)
            silent = db <= self.threshold_db

            if silent:
                if self._run_start_window is None:
                    self._run_start_window = self._current_window
                self._silent_run += 1
            else:
                self._maybe_close_run()
            self._current_window += 1

    def _maybe_close_run(self) -> None:
        if self._run_start_window is None:
            self._silent_run = 0
            return
        if self._silent_run >= self.min_silence_windows:
            start_ms = self._run_start_window * self.window_ms
            end_ms = self._current_window * self.window_ms
            self._ranges.append((start_ms, end_ms))
        self._run_start_window = None
        self._silent_run = 0

    def finalize(self) -> List[Tuple[int, int]]:
        # Flush remaining buffer as one partial window
        if self._buf:
            self.feed(bytes())
        if self._run_start_window is not None:
            self._maybe_close_run()
        return merge_ranges(self._ranges)


def detect_silence_ranges_from_pcm(
    pcm_chunks: Iterable[bytes],
    sample_rate: int,
    sample_width: int = 2,
    channels: int = 1,
    window_ms: int = 30,
    min_silence_ms: int = 800,
    threshold_db: float = -40.0,
) -> List[Tuple[int, int]]:
    det = StreamingSilenceDetector(
        sample_rate=sample_rate,
        sample_width=sample_width,
        channels=channels,
        window_ms=window_ms,
        min_silence_ms=min_silence_ms,
        threshold_db=threshold_db,
    )
    for chunk in pcm_chunks:
        det.feed(chunk)
    return det.finalize()


def scan_audio_for_silence(
    source: str,
    ffmpeg_bin: str = "ffmpeg",
    sample_rate: int = 16000,
    window_ms: int = 30,
    min_silence_ms: int = 800,
    threshold_db: float = -40.0,
    channels: int = 1,
    abort_event=None,
    detection_mode: str = "vad",
    vad_aggressiveness: int = 2,
    vad_frame_ms: int = 30,
    merge_gap_ms: int = 200,
    headers: Optional[dict] = None,
    threads: Optional[int] = None,
    low_priority: bool = False,
    position_provider: Optional[Callable[[], Optional[int]]] = None,
    lead_ms: int = 0,
    progress_callback: Optional[Callable[[List[Tuple[int, int]], int], None]] = None,
) -> List[Tuple[int, int]]:
    """
    Use ffmpeg to decode an arbitrary URL/file to PCM and detect silent spans.
    Returns a list of (start_ms, end_ms) pairs.

    detection_mode: "vad" (WebRTC VAD) or "rms" (volume-based fallback for tests).

    Pacing: with ``position_provider`` and a positive ``lead_ms``, the scan stops
    reading once it is that far ahead of the reported playback position. ffmpeg
    then blocks on its own stdout pipe, so decoding a whole episode at full
    speed the moment playback starts becomes a slow trickle that follows the
    listener. Pair it with ``progress_callback`` so partial results are usable
    while the scan is still running -- otherwise pacing would delay every
    result until the end of the file.
    """
    if not source:
        return []
    
    # Ensure PATH is set up for FFmpeg detection
    try:
        from .dependency_check import _maybe_add_windows_path, _log
        _maybe_add_windows_path()
        _log(f"Starting silence scan for: {source}")
    except Exception:
        def _log(m): pass
        pass

    if not shutil.which(ffmpeg_bin):
        _log(f"Silence scan failed: {ffmpeg_bin} not found in PATH")
        raise FileNotFoundError("ffmpeg not found in PATH")

    cmd = [
        ffmpeg_bin,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if threads is not None:
        try:
            tcount = int(threads)
        except Exception:
            tcount = None
        if tcount is not None and tcount > 0:
            cmd.extend(["-threads", str(tcount)])

    # Only pass HTTP header options for HTTP(S) URLs; local files/formats reject them.
    source_str = str(source).strip()
    source_lower = source_str.lower()
    is_http_url = source_lower.startswith("http://") or source_lower.startswith("https://")

    if is_http_url:
        # Use custom headers if provided
        if headers:
            header_str = ""
            for k, v in headers.items():
                if k.lower() == "user-agent":
                    cmd.extend(["-user_agent", str(v)])
                else:
                    header_str += f"{k}: {v}\r\n"
            if header_str:
                cmd.extend(["-headers", header_str])
        else:
            # Default user agent if none provided
            cmd.extend([
                "-user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ])

    cmd.extend([
        "-i",
        source_str,
        "-ac",
        str(channels),
        "-ar",
        str(sample_rate),
        "-f",
        "s16le",
        "-",
    ])
    import platform
    creationflags = 0
    startupinfo = None
    preexec_fn = None
    if platform.system().lower() == "windows":
        creationflags = 0x08000000 # CREATE_NO_WINDOW
        if low_priority:
            creationflags |= 0x00004000 # BELOW_NORMAL_PRIORITY_CLASS
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE
    else:
        if low_priority:
            try:
                import os

                def _nice() -> None:
                    try:
                        os.nice(10)
                    except Exception:
                        pass

                preexec_fn = _nice
            except Exception:
                preexec_fn = None

    use_vad = (detection_mode == "vad")
    if use_vad and webrtcvad is None:
        # Check before spawning ffmpeg: raising after Popen leaked a running
        # child process (ResourceWarning: subprocess ... is still running).
        raise RuntimeError("webrtcvad not available; install the webrtcvad package")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
        startupinfo=startupinfo,
        preexec_fn=preexec_fn,
    )

    detector = None
    if not use_vad:
        detector = StreamingSilenceDetector(
            sample_rate=sample_rate,
            sample_width=2,
            channels=channels,
            window_ms=window_ms,
            min_silence_ms=min_silence_ms,
            threshold_db=threshold_db,
        )
    aborted = False
    try:
        assert proc.stdout is not None
        stderr_data = b""

        bytes_per_ms = (int(sample_rate) * 2 * max(1, int(channels))) / 1000.0
        paced = bool(position_provider) and int(lead_ms) > 0

        def _pcm_iter():
            nonlocal aborted
            read_bytes = 0
            while True:
                if abort_event is not None and getattr(abort_event, "is_set", lambda: False)():
                    aborted = True
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                    return
                if paced:
                    # Stay `lead_ms` ahead of the listener and no further. While
                    # we hold off reading, ffmpeg blocks writing to the pipe, so
                    # it stops burning CPU too.
                    scanned_ms = read_bytes / bytes_per_ms if bytes_per_ms else 0.0
                    try:
                        pos_ms = position_provider()
                    except Exception:
                        pos_ms = None
                    if pos_ms is not None and scanned_ms - float(pos_ms) > float(lead_ms):
                        if abort_event is not None and getattr(abort_event, "wait", None):
                            if abort_event.wait(0.5):
                                aborted = True
                                try:
                                    proc.terminate()
                                except Exception:
                                    pass
                                return
                        else:
                            time.sleep(0.5)
                        continue
                # 64 KB, not 4 KB: the frame loop re-buffers every read, so
                # small reads multiplied both the syscall and the copy count.
                chunk = proc.stdout.read(65536)
                if not chunk:
                    return
                read_bytes += len(chunk)
                yield chunk

        ranges: List[Tuple[int, int]]
        if use_vad:
            ranges = _detect_vad_ranges(
                _pcm_iter(),
                sample_rate=sample_rate,
                frame_ms=vad_frame_ms,
                min_silence_ms=min_silence_ms,
                aggressiveness=vad_aggressiveness,
                merge_gap_ms=merge_gap_ms,
                threshold_db=threshold_db,
                progress_callback=progress_callback,
            )
        else:
            for chunk in _pcm_iter():
                detector.feed(chunk)
            ranges = detector.finalize()

        # Drain stderr to avoid blocking on wait
        try:
            if proc.stderr:
                stderr_data = proc.stderr.read() or b""
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    finally:
        # Always reap the child: an exception above (decode error, VAD
        # failure, ...) previously left ffmpeg running and its Popen
        # unwaited, which surfaces as "ResourceWarning: subprocess ... is
        # still running" at garbage collection. No-op on the normal path
        # (proc.wait already ran).
        try:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass
        try:
            if proc.stdout:
                proc.stdout.close()
        except Exception:
            pass
        try:
            if proc.stderr:
                proc.stderr.close()
        except Exception:
            pass
    if aborted:
        return []

    if proc.returncode not in (0, None):
        details = ""
        try:
            details = (stderr_data or b"").decode("utf-8", "replace").strip()
        except Exception:
            details = ""
        if details:
            raise RuntimeError(f"ffmpeg exited with code {proc.returncode}: {details}")
        raise RuntimeError(f"ffmpeg exited with code {proc.returncode}")

    return ranges
