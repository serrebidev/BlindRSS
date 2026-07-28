# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import math
import os
import shutil
import struct
import tempfile
import threading
import unittest
import wave

from core.audio_silence import (
    _detect_vad_ranges,
    detect_silence_ranges_from_pcm,
    scan_audio_for_silence,
)

try:
    import webrtcvad
except Exception:  # pragma: no cover - optional dependency
    webrtcvad = None


def _build_pcm(segments, sample_rate=16000):
    """
    segments: list of (duration_ms, amplitude_0_to_1) where amplitude is peak of a sine wave.
    """
    frames = bytearray()
    for dur_ms, amp in segments:
        samples = int(sample_rate * dur_ms / 1000.0)
        for i in range(samples):
            # Simple sine tone so RMS is predictable
            val = int(amp * 32767 * math.sin(2 * math.pi * (i / float(sample_rate)) * 440))
            frames.extend(struct.pack("<h", val))
    return bytes(frames)


class SilenceDetectionTests(unittest.TestCase):
    def test_detect_silence_from_pcm(self):
        # 0-400ms silence, 400-1100ms tone, 1100-2000ms silence, 2000-2600ms tone
        pcm = _build_pcm([
            (400, 0.0),
            (700, 0.6),
            (900, 0.0),
            (600, 0.6),
        ])

        ranges = detect_silence_ranges_from_pcm(
            [pcm],
            sample_rate=16000,
            window_ms=30,
            min_silence_ms=200,
            threshold_db=-35,
        )
        self.assertEqual(len(ranges), 2)
        first, second = ranges
        # Allow window rounding noise (+/- 40ms)
        self.assertLess(abs(first[0] - 0), 50)
        self.assertLess(abs(first[1] - 400), 60)
        self.assertLess(abs(second[0] - 1100), 80)
        self.assertLess(abs(second[1] - 2000), 80)

    def test_detect_silence_with_streaming_chunks(self):
        pcm = _build_pcm([
            (300, 0.0),
            (400, 0.7),
            (800, 0.0),
        ])
        chunks = [pcm[i:i + 2048] for i in range(0, len(pcm), 2048)]
        ranges = detect_silence_ranges_from_pcm(
            chunks,
            sample_rate=16000,
            window_ms=20,
            min_silence_ms=150,
            threshold_db=-35,
        )
        self.assertEqual(len(ranges), 2)
        self.assertLess(abs(ranges[0][0] - 0), 40)
        self.assertLess(abs(ranges[1][0] - 700), 80)

    def test_vad_framing_is_independent_of_chunk_size(self):
        """The VAD loop must frame identically however the PCM arrives.

        It buffers whatever ffmpeg hands it and slices fixed frames out by
        index; a boundary bug there would shift every timestamp after the first
        odd-sized read, so this pins byte-for-byte identical output across chunk
        sizes far smaller and larger than one frame.
        """
        if webrtcvad is None:
            self.skipTest("webrtcvad not available")

        # 8 kHz, 30 ms frames = 480 bytes per frame; the chunk sizes below sit
        # above, below, and exactly on that boundary.
        pcm = _build_pcm(
            [(600, 0.0), (900, 0.6), (1500, 0.0), (700, 0.6)],
            sample_rate=8000,
        )

        def _chunks(size):
            return (pcm[i:i + size] for i in range(0, len(pcm), size))

        reference = _detect_vad_ranges(
            _chunks(65536), sample_rate=8000, frame_ms=30, min_silence_ms=400,
            aggressiveness=0, merge_gap_ms=200, threshold_db=-38.0,
        )
        # A silent stretch must actually be found, or this proves nothing.
        self.assertTrue(reference)

        for size in (4096, 1000, 480, 481, 7):
            with self.subTest(chunk=size):
                got = _detect_vad_ranges(
                    _chunks(size), sample_rate=8000, frame_ms=30,
                    min_silence_ms=400, aggressiveness=0, merge_gap_ms=200,
                    threshold_db=-38.0,
                )
                self.assertEqual(got, reference)

    def test_vad_reports_progress_while_scanning(self):
        """Partial results must arrive during the scan, not only at the end.

        A paced scan only finishes when the listener reaches the end of the
        episode, so silence skipping depends on these intermediate publishes.
        """
        if webrtcvad is None:
            self.skipTest("webrtcvad not available")

        pcm = _build_pcm(
            [(600, 0.0), (900, 0.6), (1500, 0.0), (900, 0.6), (1500, 0.0)],
            sample_rate=8000,
        )
        seen = []
        ranges = _detect_vad_ranges(
            (pcm[i:i + 4096] for i in range(0, len(pcm), 4096)),
            sample_rate=8000, frame_ms=30, min_silence_ms=400,
            aggressiveness=0, merge_gap_ms=200, threshold_db=-38.0,
            progress_callback=lambda r, ms: seen.append((list(r), ms)),
            progress_interval_ms=500,
        )
        self.assertTrue(seen, "no progress was reported during the scan")
        # Progress is monotonic in scanned position and never reports a range
        # the final result contradicts.
        scanned = [ms for _r, ms in seen]
        self.assertEqual(scanned, sorted(scanned))
        for partial, _ms in seen:
            for span in partial:
                self.assertIn(span[0], [r[0] for r in ranges])

    def test_scan_paces_itself_to_the_listener(self):
        """With a lead time set, the scan stops reading once far enough ahead."""
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not available")
        if webrtcvad is None:
            self.skipTest("webrtcvad not available")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        path = tmp.name
        try:
            # 30 seconds of audio; the listener never moves past the start.
            pcm = _build_pcm([(2000, 0.0), (28000, 0.5)], sample_rate=8000)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(8000)
                wf.writeframes(pcm)

            reached = []
            abort = threading.Event()

            def _progress(_ranges, scanned_ms):
                reached.append(scanned_ms)
                # Once the scan is past its allowed lead, stop the test.
                if scanned_ms >= 8000:
                    abort.set()

            scan_audio_for_silence(
                path,
                sample_rate=8000,
                min_silence_ms=400,
                threshold_db=-38.0,
                detection_mode="vad",
                vad_aggressiveness=0,
                vad_frame_ms=30,
                abort_event=abort,
                position_provider=lambda: 0,   # listener parked at 0:00
                lead_ms=5000,
                progress_callback=_progress,
            )

            self.assertTrue(reached, "scan never reported progress")
            # It may overshoot by one read (64 KB = 4s at 8 kHz) plus a progress
            # interval, but it must not have raced to the end of the file.
            self.assertLess(max(reached), 20000)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    def test_scan_audio_with_ffmpeg_when_available(self):
        if not shutil.which("ffmpeg"):
            self.skipTest("ffmpeg not available")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp.close()
        path = tmp.name

        try:
            pcm = _build_pcm([
                (500, 0.0),
                (700, 0.5),
                (600, 0.0),
            ])
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(pcm)

            ranges = scan_audio_for_silence(
                path,
                sample_rate=16000,
                window_ms=30,
                min_silence_ms=300,
                threshold_db=-38,
                detection_mode="rms",
            )
            self.assertEqual(len(ranges), 2)
            self.assertLess(abs(ranges[0][0] - 0), 60)
            self.assertLess(abs(ranges[1][0] - 1200), 120)
        finally:
            try:
                os.remove(path)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
