# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Small, pkg_resources-free wrapper for the WebRTC VAD extension.

``webrtcvad-wheels`` still imports ``pkg_resources`` solely to discover its
version.  Modern, security-patched setuptools no longer ships that legacy API,
even though the package's ``_webrtcvad`` native extension remains fully
functional.  BlindRSS only needs the public ``Vad`` interface, so keep that
interface here and talk to the extension directly.
"""

import _webrtcvad


class Vad:
    def __init__(self, mode=None):
        self._vad = _webrtcvad.create()
        _webrtcvad.init(self._vad)
        if mode is not None:
            self.set_mode(mode)

    def set_mode(self, mode):
        _webrtcvad.set_mode(self._vad, mode)

    def is_speech(self, buf, sample_rate, length=None):
        length = length or int(len(buf) / 2)
        if length * 2 > len(buf):
            raise IndexError(
                f"buffer has {int(len(buf) / 2.0)} frames, "
                f"but length argument was {length}"
            )
        return _webrtcvad.process(self._vad, sample_rate, buf, length)


def valid_rate_and_frame_length(rate, frame_length):
    return _webrtcvad.valid_rate_and_frame_length(rate, frame_length)
