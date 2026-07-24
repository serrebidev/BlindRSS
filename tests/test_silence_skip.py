# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import math
import os
import shutil
import struct
import tempfile
import unittest
import wave

from core.audio_silence import detect_silence_ranges_from_pcm, scan_audio_for_silence


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
