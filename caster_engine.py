# Vendored from Caster 0.5.23 (e293ec0) by tools/sync_caster.py.
# GUI-free engine section of caster.py.
# Do not edit: fix it in Caster and run tools/sync_caster.py again.
"""Caster's streaming engine: probing, HLS relay, live TS reader, device model.

Extracted verbatim from Caster's caster.py; see tools/sync_caster.py.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import functools
import http.server
import io
import mimetypes
import os
import math
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any, Optional
from caster_extras import upnp_host


#: Diagnostic timeline, off unless CASTER_TRACE names a file. Buffering is a
#: timing problem and timing problems are invisible from a status bar, so this
#: records what happened and when: every probe, every encoder, every state the
#: receiver reported. Costs one environment lookup when it is off.
_TRACE_PATH = os.environ.get("CASTER_TRACE", "")
_trace_lock = threading.Lock()
_trace_t0 = time.monotonic()


_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")


def _redact_urls(text: str) -> str:
    """Strip source URLs out of anything that may be written down.

    An IPTV URL carries the subscription's username and password in its own
    path. ffmpeg names its input in most of its errors, so a diagnostic that
    quotes ffmpeg verbatim would publish those credentials into a trace file.
    """
    return _URL_RE.sub("<source>", text)


def trace(event: str, detail: str = "") -> None:
    if not _TRACE_PATH:
        return
    line = (f"{time.monotonic() - _trace_t0:8.2f}s  "
            f"{threading.current_thread().name:22} {event:26} {detail}\n")
    try:
        with _trace_lock:
            with open(_TRACE_PATH, "a", encoding="utf-8") as handle:
                handle.write(line)
    except OSError:
        pass

#: How long each discovery protocol listens for replies. SSDP and mDNS
#: answer over a few seconds rather than at once, so this is the floor on
#: how quick a scan can be -- and, because the protocols now run in
#: parallel, very nearly the whole cost of one.
DISCOVER_SECONDS = 5

YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/)([A-Za-z0-9_-]{6,})"
)


def youtube_id(url: str) -> Optional[str]:
    m = YT_ID_RE.search(url)
    return m.group(1) if m else None


def url_path(url: str) -> str:
    """The URL with its query and fragment removed."""
    return url.split("?")[0].split("#")[0]


def guess_mime(url: str) -> str:
    mt, _ = mimetypes.guess_type(url_path(url))
    if mt:
        return mt
    if "aac" in url.lower():
        return "audio/aac"
    # Nothing in the URL says what this is. Radio streams are the common
    # extension-less case, so audio is the useful guess -- but it is only a
    # guess, which is why probe_media leaves is_audio unknown rather than
    # treating it as a fact. See the fallback branch there.
    return "audio/mpeg"


def roku_mime(url: str) -> str:
    """The media type to tell Roku Media Player for a plain URL.

    Roku has to be told the format up front. Defaulting every URL to MP4 sent
    HLS playlists and audio links to its video player labelled as MP4.
    """
    path = url_path(url).lower()
    if path.endswith((".m3u8", ".m3u")):
        return "application/vnd.apple.mpegurl"
    mt, _ = mimetypes.guess_type(path)
    if mt in ("audio/x-wav", "audio/wave"):
        return "audio/wav"
    if mt and mt.startswith("audio/"):
        return mt
    return "video/mp4"


# Content-Type prefixes mapped to (mime, is_audio) for extension-less URLs
# (IPTV portals, provider VOD links, etc.).
_CT_VIDEO = {"video/mp4", "video/webm", "video/mp2t", "video/mpeg",
             "video/x-matroska", "video/quicktime", "video/x-msvideo"}
_CT_AUDIO = {"audio/mpeg", "audio/aac", "audio/aacp", "audio/mp4", "audio/x-m4a",
             "audio/ogg", "audio/flac", "audio/x-flac", "audio/wav", "audio/x-wav"}


#: Bytes read to identify a stream. Enough to find the packet stride several
#: times over even when the response begins mid-packet.
PROBE_BYTES = 2048
#: URL inspection selects a safe transport path, but must not turn five
#: individual socket timeouts into a minute of silence before playback starts.
PROBE_ATTEMPT_TIMEOUT = 3.0
PROBE_TOTAL_TIMEOUT = 8.0


def _looks_like_mpegts(head: bytes) -> bool:
    """Whether these bytes are really MPEG-TS.

    The sync byte is 0x47, which is also ASCII "G", so on its own it says
    almost nothing: a text file, a subtitle or a GIF starting with that
    letter all pass it. What identifies the format is the byte repeating at
    the packet stride -- every 188 bytes, or every 192 for M2TS.

    The stride is what to look for, but NOT at byte 0. A live server does not
    owe anyone a packet boundary: the stream is joined mid-flight, so byte 0
    is wherever the connection happened to land. Demanding the sync byte
    there misread one provider's live channels about a third of the time --
    as audio/mpeg, off a chance 0xff 0xfb pair in the payload -- and a live
    channel misread as VOD loses the piped reader, the replay dedupe and the
    under-feed rotation all at once. That was an encoder restarting 26 times
    in 70 seconds against a server which then refused it outright.

    So find an offset whose stride repeats. Four consecutive hits is not a
    coincidence any text or image will produce, and too few bytes to prove a
    stride stays an unproven claim rather than a generous one.
    """
    # An aligned buffer proves itself at byte 0 with one stride, which is
    # all a short local file can offer and what this has always accepted.
    if head.startswith(b"G"):
        if len(head) >= 189 and head[188] == 0x47:
            return True                 # 188-byte packets
        if len(head) >= 193 and head[192] == 0x47:
            return True                 # M2TS
    # A mid-packet start has to be searched for, so it is held to more
    # proof: scanning every offset makes a two-hit coincidence far too
    # cheap (about 1 in 340 on random bytes), while four is out of reach.
    for stride in (188, 192):
        for start in range(1, stride):
            if start + 3 * stride >= len(head):
                break
            if all(head[start + n * stride] == 0x47 for n in range(4)):
                return True
    return False


#: Longest segment a portal's own HLS playlist may contain before Caster
#: serves the channel through its own relay instead. A receiver that reaches
#: the live edge waits for the next segment to finish, so segment length is
#: the worst-case stall, and the relay's own segments are hls_time long (2s).
#: Measured 2026-09-08 on one portal: three channels' native playlists ran
#: 9.9-16.7s per segment against a 6-segment window, one of them advertising
#: TARGETDURATION 17 then 12, while the relay served the same channel in
#: steady 2.00s segments. 8s sits above ordinary practice (6s is the usual
#: convention, and Apple's authoring guidance recommends it) and below every
#: one of those, so a portal that builds its playlist normally is still
#: preferred and one that cannot be played smoothly is not.
NATIVE_HLS_SEGMENT_LIMIT = 8.0


def _native_hls_url(url: str) -> Optional[str]:
    """Validate a live IPTV portal's sibling HLS feed before remuxing TS.

    Some portals replay buffered TS whenever a connection is reopened. Their
    HLS endpoint supplies stable sequence numbers instead. Only try the
    numeric channel URL convention, and keep the TS fallback for everything
    that does not return an actual live media playlist.

    Preferring that feed is worth it only while it plays better than what the
    relay would build. TsSource now hides the replay this preference was
    introduced to dodge, so a portal playlist whose segments are long enough
    to stall the receiver has nothing left to offer over the relay.
    """
    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return None
    if not re.fullmatch(r"/(?:live/)?[^/]+/[^/]+/\d+\.ts", parts.path,
                        flags=re.IGNORECASE):
        return None
    candidate = urllib.parse.urlunsplit(parts._replace(path=parts.path[:-3] + ".m3u8"))
    try:
        req = urllib.request.Request(candidate, headers={"User-Agent": "caster/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            body = response.read(65537)
        if len(body) > 65536:
            return None
        lines = body.decode("utf-8-sig").splitlines()
        if (lines and lines[0] == "#EXTM3U"
                and any(line.startswith("#EXT-X-TARGETDURATION:") for line in lines)
                and any(line.startswith("#EXTINF:") for line in lines)
                and any(line and not line.startswith("#") for line in lines)
                and "#EXT-X-ENDLIST" not in lines):
            # Judge the durations it actually lists, not the TARGETDURATION
            # it advertises: that tag has been seen both understating the
            # segments below it and changing between reloads.
            longest = 0.0
            for line in lines:
                if line.startswith("#EXTINF:"):
                    try:
                        longest = max(longest, float(
                            line.split(":", 1)[1].split(",")[0]))
                    except ValueError:
                        return None    # unparsable playlist; use the relay
            if longest > NATIVE_HLS_SEGMENT_LIMIT:
                return None
            return candidate
    except (OSError, ValueError, UnicodeError):
        pass
    return None


def probe_media(url: str) -> dict:
    """Probe a URL for content type, audio-ness and live-ness.

    Magic bytes win over headers: IPTV servers lie about Content-Type
    (e.g. video/mp4 for raw MPEG-TS). Reads 193 bytes so both 188-byte TS
    and 192-byte M2TS sync patterns are visible.
    """
    result = {"url": url, "mime": guess_mime(url), "is_audio": None,
              "is_live": False}
    if not url.lower().startswith(("http://", "https://")):
        # Local file: decide from extension + magic bytes directly.
        path = url
        mt, _ = mimetypes.guess_type(path)
        if os.path.splitext(path)[1].lower() == ".wav":
            mt = "audio/wav"
        mime = mt or "application/octet-stream"
        result["mime"] = mime
        result["is_audio"] = mime.startswith("audio/")
        result["is_live"] = False
        try:
            with open(path, "rb") as f:
                head = f.read(PROBE_BYTES)
            # One sync byte proves nothing: 0x47 is also ASCII "G", so a
            # local file that merely begins with that letter was being
            # sent down the live-remux path. Confirm the packet stride,
            # exactly as the HTTP branch does.
            if _looks_like_mpegts(head):
                result["mime"], result["is_audio"], result["is_live"] = \
                    "video/mp2t", False, False
        except OSError:
            pass
        return result
    req = urllib.request.Request(url, headers={"User-Agent": "caster/1.0",
                                               "Range": f"bytes=0-{PROBE_BYTES - 1}"})
    # One sample decides whether this is treated as a live channel, and that
    # is too much weight for a single reply from a load-balanced CDN. One
    # provider answers the same URL from several nodes, and some of them
    # return HTTP 200 with a zero-byte body or a 503: measured 2026-09-08,
    # three of six requests were unusable. An empty body has no magic bytes,
    # so the lying Content-Type wins, is_live goes False, and the channel
    # loses the piped reader, the replay dedupe and the under-feed rotation
    # in one go -- an encoder restarting 26 times in 70 seconds. Ask again
    # instead of believing an answer that told us nothing.
    ct = ""
    head = b""
    deadline = time.monotonic() + PROBE_TOTAL_TIMEOUT
    for attempt in range(5):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            with urllib.request.urlopen(
                    req, timeout=min(PROBE_ATTEMPT_TIMEOUT, remaining)) as r:
                body = r.read(PROBE_BYTES)
                body_ct = (r.headers.get("Content-Type")
                           or "").split(";")[0].strip().lower()
        except Exception:
            body, body_ct = b"", ""
        if len(body) > len(head):
            head, ct = body, body_ct
        # Enough bytes to prove a packet stride is enough to decide on, and
        # a URL that really is not MPEG-TS answers in full first time, so
        # this costs one request for everything that is working.
        if len(head) >= 3 * 188 + 1:
            break
        if attempt < 4:
            # 503s arrive in clusters, but a retry has no value once the
            # bounded probe budget is exhausted.
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.3 * 2 ** attempt, remaining))
    if ct in ("application/vnd.apple.mpegurl", "application/x-mpegurl"):
        result["mime"] = ct
        result["is_audio"] = False
        result["is_live"] = True
        return result
    is_audio = None
    if _looks_like_mpegts(head):
        # MPEG-TS sync bytes: live IPTV channel, whatever the header claims
        is_audio, mime = False, "video/mp2t"
    elif head.startswith(b"ID3") or head.startswith(b"\xff\xfb") or head.startswith(b"\xff\xf3"):
        is_audio, mime = True, "audio/mpeg"
    elif head.startswith(b"OggS"):
        is_audio, mime = True, "audio/ogg"
    elif head.startswith(b"fLaC"):
        is_audio, mime = True, "audio/flac"
    elif head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        is_audio, mime = True, "audio/wav"
    elif head[4:8] == b"ftyp":
        is_audio, mime = False, "video/mp4"
    elif ct in _CT_AUDIO:
        is_audio, mime = True, ct
    elif ct in _CT_VIDEO:
        is_audio, mime = False, ct
    else:
        mime = result["mime"]
        is_audio = mime.startswith("audio/")

    result["mime"] = mime
    result["is_audio"] = is_audio
    # MPEG-TS over HTTP is a live channel (segmented streams aside);
    # true VOD responses report Content-Length.
    result["is_live"] = mime == "video/mp2t"
    if not head and not ct:
        # Every attempt failed, so nothing above was measured -- `mime` is
        # guess_mime()'s reading of the URL, and for an extensionless portal
        # URL that guess is audio/mpeg out of thin air. Calling a stream VOD
        # on no evidence is the expensive mistake: it drops the piped reader,
        # the replay dedupe and the under-feed rotation, and the plain path
        # then restarted an encoder 26 times in 70 seconds. Treating it as
        # live only turns those protections on. The cost of being wrong the
        # other way is a finite asset getting reconnect handling it does not
        # need, which is survivable; this is not.
        result["is_live"] = True
    return result


def _no_window_kwargs() -> dict:
    """kwargs that keep any spawned subprocess fully windowless on Windows
    (no console flash, no taskbar entry, non-interactive)."""
    import sys
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0  # SW_HIDE
        return {
            "startupinfo": si,
            "creationflags": (
                subprocess.CREATE_NO_WINDOW
                | subprocess.CREATE_BREAKAWAY_FROM_JOB
            ),
        }
    return {}


def _find_ffmpeg() -> str:
    """Locate ffmpeg: bundled (frozen exe) first, PATH, then winget."""
    import shutil
    import sys
    if getattr(sys, "frozen", False):
        bundled = os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
        if os.path.exists(bundled):
            return bundled
    found = shutil.which("ffmpeg")
    if found:
        return found
    import glob
    for pattern in (
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\**\bin\ffmpeg.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\*ffmpeg*\**\bin\ffmpeg.exe"),
    ):
        for hit in glob.glob(pattern, recursive=True):
            return hit
    raise FileNotFoundError("ffmpeg.exe not found next to the app, on PATH, or in winget packages")


_ENC_CANDIDATES = ("h264_qsv", "h264_amf", "h264_nvenc", "h264_mf", "libx264")
_encoder_cache: Optional[str] = None
_encoder_lock = threading.Lock()
ENCODER_PROBE_TIMEOUT = 2.5
ENCODER_PROBE_BUDGET = 8.0


def pick_h264_encoder() -> str:
    """Pick the fastest working H.264 encoder by timing a 2s 720p encode.
    Chain order alone lies (nvenc beats mf in toy tests but crawls on some
    boxes); and a tiny test lies the other way (libx264 wins toy tests but
    cannot sustain live). Real-size timing + realtime requirement does not.
    Result is cached."""
    global _encoder_cache
    if _encoder_cache:
        return _encoder_cache
    # A capture warms this while the receiver launches, and the stream's own
    # connection may ask at the same moment: one probe, not two.
    with _encoder_lock:
        if _encoder_cache:
            return _encoder_cache
        return _pick_h264_encoder_locked()


def _pick_h264_encoder_locked() -> str:
    global _encoder_cache
    ff = _find_ffmpeg()
    results = {}
    deadline = time.monotonic() + ENCODER_PROBE_BUDGET
    for enc in _ENC_CANDIDATES:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        args = [
            ff, "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i",
            "testsrc2=duration=2:size=1280x720:rate=30",
            "-c:v", enc, "-f", "null", "-",
        ]
        try:
            t0 = time.monotonic()
            p = subprocess.run(args, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               timeout=min(ENCODER_PROBE_TIMEOUT, remaining),
                               **_no_window_kwargs())
            dt = time.monotonic() - t0
            if p.returncode == 0:
                results[enc] = dt
        except Exception:
            pass
    if not results:
        _encoder_cache = "libx264"
        return _encoder_cache
    best = min(results, key=lambda e: results[e])
    _encoder_cache = best
    return best


def _probe_codecs(url: str, timeout: float = 8.0) -> list:
    """Return codec names for the URL's streams (video first). Parses the
    `ffmpeg -i` banner. Empty list on failure.

    Bounded twice over, because this runs in the connect path. ffmpeg is told
    how little of the stream to inspect -- the defaults spend five seconds
    analysing an MPEG-TS before saying a word -- and it is killed outright if
    it stops talking. A server that accepts the connection and then goes
    quiet would otherwise block this read with no timeout at all.
    """
    import re as _re
    import subprocess as _sp
    args = [_find_ffmpeg(), "-hide_banner",
            "-analyzeduration", "2000000", "-probesize", "2000000",
            "-i", url]
    try:
        done = _sp.run(args, stdout=_sp.DEVNULL, stderr=_sp.PIPE,
                       stdin=_sp.DEVNULL, timeout=timeout,
                       **_no_window_kwargs())
        raw = done.stderr
    except _sp.TimeoutExpired as exc:
        raw = exc.stderr or b""     # whatever it managed before the kill
    except OSError:
        return []
    banner = raw.decode("utf-8", "replace") if raw else ""
    codecs = []
    for m in _re.finditer(
            r"Stream #0:\d+\S*\[?[^:]*\]?: (Video|Audio): (\w+)", banner):
        c = m.group(2).lower()
        if c not in codecs:
            codecs.append(c)
    return codecs


class _Sink:
    """The encoder's stdin, swappable while something else is writing to it.

    TsSource outlives any one ffmpeg: if the encoder is ever replaced, the
    reader must not notice, and must never write into a closed pipe.
    """

    def __init__(self) -> None:
        self._file = None
        self._lock = threading.Lock()

    def attach(self, file) -> None:
        with self._lock:
            previous, self._file = self._file, file
        if previous is not None and previous is not file:
            # Dispose of the replaced pipe here rather than leaving it to the
            # garbage collector. Its encoder has already been killed, so the
            # buffered flush that finalisation attempts fails -- and it fails
            # outside every handler that could deal with it, surfacing as an
            # unraisable "OSError: [Errno 22] Invalid argument" during
            # interpreter shutdown. write() swallows the same error; this is
            # the one path that could not.
            try:
                previous.close()
            except (OSError, ValueError):
                pass

    def write(self, data: bytes) -> None:
        with self._lock:
            file = self._file
        if file is None:
            return
        try:
            file.write(data)
            file.flush()
        except (OSError, ValueError):
            pass    # encoder gone; _supervise brings up the next one


class TsSource(threading.Thread):
    """A live MPEG-TS URL presented to ffmpeg as one unbroken byte stream.

    These IPTV servers close the connection every few seconds, and the next
    one does not resume where the last stopped: it starts from the server's
    own buffer, several seconds behind. Measured on 2026-09-07: connections
    lasting 3-9 seconds, each replaying 4.3 seconds already delivered. Handed
    straight to ffmpeg -- either as its own reconnect or as a fresh process --
    that made roughly half of everything the receiver played a repeat, which
    is what "it keeps jumping backwards" was.

    The replayed bytes are byte-for-byte identical to the ones already sent,
    so the overlap can simply be found and dropped. Reconnecting here rather
    than in ffmpeg means the encoder sees one continuous stream, never exits,
    and never has to be restarted -- so there is no seam to paper over with a
    discontinuity and no priming pause on the receiver.
    """

    #: Bytes of already-forwarded stream kept to recognise a replay in. Must
    #: comfortably exceed the server's buffer depth. A missed match is not a
    #: dropped frame but the "it keeps jumping backwards" bug, so the window
    #: is sized for the worst replay seen and then some: rotating for
    #: throughput reconnects far more often than the server's own drops did,
    #: and the replay grows with the reconnect rate. Measured 2026-09-08 at a
    #: ~10s rotation cadence, replays reached 5.7 MB against a 3.58 Mb/s
    #: channel -- 1.4x margin on the old 8 MB. 16 MB is ~36s at that
    #: bitrate. It is a bounded window, not a recording.
    OVERLAP_KEEP = 16 << 20
    #: How much of a new connection to match. Long enough that a coincidental
    #: match is impossible, short enough to decide within one read.
    PROBE = 32 << 10
    CHUNK = 64 << 10
    RECONNECT_DELAY = 0.2
    OPEN_TIMEOUT = 15

    def __init__(self, url: str, sink: _Sink) -> None:
        super().__init__(daemon=True, name="caster-ts-source")
        self.url = url
        self.sink = sink
        self._stop = threading.Event()
        self._tail = b""
        #: Held across forward-and-remember, so attach_with_replay() can hand
        #: a new encoder the tail and then the live stream with no byte
        #: missing or doubled at the join.
        self._forward_lock = threading.Lock()
        self._response = None
        self.reconnects = 0     # diagnostics
        self.deduped = 0        # bytes of replay dropped (diagnostics)

    def stop(self) -> None:
        self._stop.set()
        self.rotate()

    def rotate(self) -> None:
        """Drop the current connection; run() opens the next one.

        This is what an under-fed relay needs. Killing the encoder used to be
        the way to get a fresh connection, and on the piped path it no longer
        is: ffmpeg is not the thing holding the socket any more.
        """
        response, self._response = self._response, None
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._one_connection()
            except Exception as exc:
                trace("ts.error", type(exc).__name__)
            if self._stop.is_set():
                break
            self.reconnects += 1
            self._stop.wait(self.RECONNECT_DELAY)

    def _one_connection(self) -> None:
        request = urllib.request.Request(
            self.url, headers={"User-Agent": "Lavf/62.0.102"})
        with urllib.request.urlopen(request,
                                    timeout=self.OPEN_TIMEOUT) as response:
            self._response = response
            first = b""
            while len(first) < self.PROBE and not self._stop.is_set():
                chunk = response.read(self.CHUNK)
                if not chunk:
                    break
                first += chunk
            skip = self._overlap(first)
            if skip:
                self.deduped += skip
                trace("ts.dedupe", f"dropped {skip} replayed bytes")
            while not self._stop.is_set():
                if skip >= len(first):
                    skip -= len(first)
                else:
                    self._forward(first[skip:])
                    skip = 0
                first = response.read(self.CHUNK)
                if not first:
                    return

    def _overlap(self, first: bytes) -> int:
        """Bytes at the head of a new connection already sent from the last.

        Zero when nothing matches: either the server picked up where it left
        off, or it jumped so far back that the window no longer holds the
        join. Forwarding is the safe answer in both cases -- a duplicate is
        survivable, a hole in an MPEG-TS is not.
        """
        if not self._tail or len(first) < 1024:
            return 0
        # rfind, never find: a run of MPEG-TS null packets is identical
        # wherever it appears, so an early match would claim an overlap
        # bigger than the real one and cut a hole in the stream. The latest
        # match is the smallest claim, and a small duplicate is survivable.
        index = self._tail.rfind(first[:self.PROBE])
        if index < 0:
            return 0
        return len(self._tail) - index

    def _forward(self, data: bytes) -> None:
        with self._forward_lock:
            self.sink.write(data)
            self._tail = (self._tail + data)[-self.OVERLAP_KEEP:]

    def attach_with_replay(self, file, limit: int) -> None:
        """Point the sink at a new encoder, starting it on recent history.

        Only for an encoder that replaces one whose output was thrown away
        before anything was served. Its media then arrives at network speed
        from memory instead of real time from the provider: re-priming
        after the keyframe switch waited ~24s for media this reader had
        already received. Replaying into an encoder whose predecessor's
        segments were served would play them twice.
        """
        with self._forward_lock:
            self.sink.attach(file)
            if self._tail:
                self.sink.write(self._tail[-limit:])


class HlsRelay:
    """Remux/transcode an MPEG-TS stream to HLS and serve it on a local port
    so a network receiver can play it.

    ffmpeg is killed and the server closed by stop(); nothing runs when idle.
    """

    # History the receiver is shown. The playlist keeps its newest entries;
    # it does NOT hide the live edge. startup_seconds and an explicit Cast
    # start position provide the initial playback cushion. Longer history
    # lets a lagging receiver recover without losing the segment it needs.
    TRAIL_KEEP = 6
    #: The same cushion as a floor in seconds. A segment count is the wrong
    #: unit when the source cuts on its own keyframes: measured on one live
    #: channel, eight segments was anywhere from 25 to 40 seconds while the
    #: input arrived in bursts up to 13 seconds apart. Whichever of the two
    #: is deeper wins.
    TRAIL_SECONDS = 45.0

    #: Sustained under-feed detection. Some IPTV CDNs cap a connection's
    #: throughput by age: it opens at full rate and decays (measured at 0.44x
    #: sustained on one live provider, 2026-09-05). A slow encoder does not drop --
    #: it just produces slower than real time, the relay's trail drains, and
    #: the receiver stalls with nothing on this side noticing. The cure is a
    #: fresh connection, which opens hot again: kill the starved encoder and
    #: let the supervisor's restart path bring one up in place (same dir,
    #: continuing numbering, monotonic playlist). Conservative by design: two
    #: Sustained under-feed rotation applies only to caller-certified live
    #: HTTP sources, after a short startup grace period and no more than once
    #: per 90 seconds.
    # A receiver consumes one media-second per wall-second.  Waiting for the
    # old 0.55x threshold meant an 18-second Cast cushion had already drained
    # before a throttled source was rotated.  Detect ordinary under-feed while
    # there is still room to reconnect; rotate a truly starved feed at once.
    ROTATE_RATIO = 0.85      # sustained media-seconds per wall-second
    ROTATE_HARD_RATIO = 0.60 # one window: cushion would otherwise run out
    #: The piped path's sustained threshold. A socket swap costs no seam, so
    #: it can afford to act on a connection that is only slightly slow.
    #: Measured 2026-09-15 on the Big Bang channel to RB Room: the provider
    #: held ONE connection for minutes (0 reconnects) while it decayed to
    #: 0.87-0.93x. Every window cleared 0.85, so nothing rotated, and a
    #: receiver consuming 1.0x reached the live edge every minute or two --
    #: freezes of 14s and 42s. Below real time is below real time: any
    #: sustained shortfall drains the cushion, only the rate differs.
    ROTATE_RATIO_PIPED = 0.95
    #: The measurement window. It cannot be shortened to chase a faster
    #: rotation cadence: a source that delivers in bursts is idle between
    #: them, and a window shorter than its burst period can land entirely
    #: inside one gap and read 0x on a perfectly healthy stream. One
    #: provider (2026-09-08) bursts at up to 131 Mb/s with gaps to 10.6s
    #: between them while tracking real time exactly; a 10s window rotated
    #: it twice in three minutes for no reason, a 15s window not once in
    #: four. `3 * longest segment` covers a long GOP; this covers bursty
    #: delivery, which the segment length says nothing about.
    ROTATE_EVAL = 15.0
    ROTATE_STREAK = 2        # ordinary under-feed needs confirmation
    #: Rotation costs what the path costs. Killing the encoder buys a fresh
    #: connection at the price of a restart, a discontinuity and a priming
    #: pause, so it stays rare. On the piped path (TsSource) it is a socket
    #: swap: ffmpeg never notices, there is no seam, and the only cost is the
    #: ~2s connect and whatever replay the dedupe cannot drop. The old single
    #: 90s floor priced both the same and throttled the cheap one to match
    #: the expensive one.
    #:
    #: Measured against one provider (2026-09-08), unique deduplicated feed
    #: against a 3.58 Mb/s channel, by how long each connection was held:
    #: 8s -> 2.27x, 15s -> 1.20x, 30s -> 0.89x, never -> 0.57x. The server
    #: opens hot and decays within ~10 seconds, and the cap is per
    #: connection, not per account: two simultaneous connections each ran at
    #: the full opening rate. Holding one for 90s therefore guaranteed a
    #: 0.57x feed -- the cushion drained about once every 90s, which is what
    #: "it buffers once in a while" was. ROTATE_EVAL bounds how often the
    #: verdict can arrive, so the real cadence is ~15s and the feed it buys
    #: is 1.20x: less than a 8s cadence would give, and the most that can be
    #: taken without misjudging a bursty source.
    ROTATE_MIN_AGE = 30.0    # let a fresh connection settle before judging it
    ROTATE_MIN_GAP = 90.0    # floor between forced rotations
    ROTATE_MIN_AGE_PIPED = 12.0  # a socket swap needs no settling time
    ROTATE_MIN_GAP_PIPED = 10.0  # match a provider that decays in ~10s
    #: Longest completed segment a stream copy may produce before the video
    #: is re-encoded with forced keyframes. With -c copy a segment can only
    #: end on a keyframe, so segment length IS the source GOP, and a channel
    #: that emits one every 8s forces 8s segments -- the receiver then waits
    #: that long at the live edge, heard as a stall of exactly that length.
    #: Measured on one channel: keyframes 1.0s to 7.7s apart, 27% over 4s,
    #: served segments up to 8.9s, reported as 3-7 second buffering. A clean
    #: channel sits at hls_time (2s here) and never trips this; the two other
    #: providers measured ran 2.0-2.6s median with a 4.1s worst case, so the
    #: limit is set above them: only a source a copy cannot serve is
    #: re-encoded.
    GOP_COPY_LIMIT = 5.0
    #: Live URLs whose GOP needed keyframes placed, for this session.
    _keyframe_urls: set = set()
    #: Recent source bytes handed to an encoder that replaces a discarded
    #: prime. 8 MiB is ~18s at the 3.58 Mb/s channel measured here; ffmpeg
    #: resyncs on the packet boundary and waits for the first keyframe.
    PRIME_REPLAY_BYTES = 8 << 20
    #: Lines of ffmpeg diagnostics kept for the last exit. A stuck encoder
    #: can print one warning per frame, so this is a ring, not a log.
    STDERR_KEEP = 40

    def __init__(self, url: str, hls_time: int = 2, prime_segments: int = 3,
                 trail_keep: int = TRAIL_KEEP, codecs: Optional[list] = None,
                 live: Optional[bool] = None,
                 trail_seconds: float = TRAIL_SECONDS,
                 startup_seconds: float = 0.0) -> None:
        self.url = url
        #: Segment length. Shorter means the receiver can start sooner, since
        #: everything below is counted in segments, not seconds.
        self.hls_time = max(1, int(hls_time))
        #: Segments to accumulate before the URL is handed over. Three is the
        #: floor, not a preference: it is what clears 3x TARGETDURATION.
        self.prime_segments = max(3, int(prime_segments))
        self.trail_keep = max(3, int(trail_keep))
        self.trail_seconds = max(0.0, float(trail_seconds))
        self.startup_seconds = max(0.0, float(startup_seconds))
        self.play_url = None
        #: Stream codecs, when the caller has already paid to find them out.
        #: Probing costs a whole extra connection to the source, and IPTV
        #: servers are slow to accept one and slower to authorise it.
        self.codecs = codecs
        self.proc = None
        self.httpd = None
        self.port = 0
        self.root = None
        self.video_transcoded = False  # True: source video not H.264
        #: True: re-encode H.264 video purely to place keyframes, because the
        #: source's own are too far apart to cut regular segments on. A live
        #: channel already found to need it this session starts that way:
        #: finding out again costs a copy prime that is thrown away.
        self.force_keyframes = bool(live) and url in HlsRelay._keyframe_urls
        self._trail_drop = None   # segments hidden from the served playlist
        self._last_good = None    # last known-good playlist bytes
        #: Highest EXT-X-MEDIA-SEQUENCE ever served. An HLS client treats a
        #: sequence that goes backwards as an instruction to replay, so this
        #: is a ratchet: whatever ffmpeg's own numbering does across a
        #: restart, what leaves here never decreases.
        self._served_seq = None
        #: Highest EXT-X-TARGETDURATION ever served, for the same reason: the
        #: spec forbids it changing, and ffmpeg varies it on an irregular GOP.
        self._served_target = None
        self._restarted = 0       # upstream-drop restarts (diagnostics)
        #: True only when the caller certifies the source is live. Under-feed
        #: rotation restarts a connection from the live edge, which for a VOD
        #: or local file would restart the media from the beginning.
        self.live = live
        self._rotated = 0        # forced under-feed rotations (diagnostics)
        self._last_rotate = 0.0
        self._fail_streak = 0
        self._eval_t0 = None     # (monotonic, newest-seg) window start
        self._proc_born = 0.0
        #: Segment numbers where a restarted encoder began. Each is served
        #: with an #EXT-X-DISCONTINUITY tag: a fresh upstream connection
        #: continues the channel but not its timestamp clock, and a receiver
        #: told to treat the two timelines as one splices them into a replay
        #: of the last few seconds followed by a decode failure.
        self._discont_segs: set = set()
        self._playlist_lock = threading.Lock()
        #: ffmpeg's own last words, kept so an exit can be explained. Every
        #: encoder death so far has been silent: stderr went to DEVNULL, so
        #: "why did the stream skip" had no answer beyond an exit code.
        self._stderr_tail: collections.deque = collections.deque(
            maxlen=self.STDERR_KEEP)
        #: Set when this relay reads the source itself and pipes it in. See
        #: TsSource: it exists to hide a provider that reconnects constantly
        #: and replays what it already sent.
        self.ts_source = None
        self._sink = None

    def piped_source(self) -> bool:
        """Whether to read the source here and pipe it into ffmpeg.

        Only for a live raw stream over HTTP. A playlist source (.m3u8) is a
        series of separate requests that ffmpeg has to make itself, and a
        local file never drops, so neither has anything to gain.
        """
        if not self.live:
            return False
        url = self.url.lower().split("?")[0]
        if not url.startswith(("http://", "https://")):
            return False
        return not url.endswith((".m3u8", ".m3u"))

    def start(self, prime_segments: int = 0) -> str:
        import tempfile
        want = max(3, int(prime_segments or self.prime_segments))
        self.root = tempfile.mkdtemp(prefix="caster_hls_")
        try:
            handler = functools.partial(HlsFileHandler, directory=self.root)
            # ThreadingHTTPServer + HTTP/1.1 keep-alive: the receiver reuses
            # one connection for playlist polls and segment fetches instead of
            # a new TCP handshake per request (visible as mid-playback stalls).
            self.httpd = http.server.ThreadingHTTPServer(("0.0.0.0", 0),
                                                         handler)
            self.httpd.relay = self
            self.port = self.httpd.server_address[1]
            threading.Thread(target=self.httpd.serve_forever, daemon=True,
                             name="caster-hls").start()

            m3u8 = os.path.join(self.root, "live.m3u8")
            self._spawn_ffmpeg()
            long_copy_gop = self._prime(m3u8, want)
            # Priming has just measured the source's GOP for free: with
            # -c copy a segment can only end on a keyframe, so the segments
            # sitting on disk ARE the keyframe spacing. If they are too long
            # to serve, re-encode with keyframes we place ourselves.
            #
            # Decide HERE, before the receiver has the URL. The same switch
            # made later is a mid-stream discontinuity and a rebuffer; made
            # now it is invisible, and the only cost is priming twice. The
            # source connection is not one of the things thrown away: on the
            # piped path TsSource outlives the encoder.
            if (not self.force_keyframes
                    and (long_copy_gop or self._copy_gop_too_long())):
                longest = max(self._completed_segments().values())
                trace("relay.keyframes",
                      f"source segments reach {longest:.1f}s (limit "
                      f"{self.GOP_COPY_LIMIT:.0f}s); re-encoding video to "
                      f"place keyframes every {self.hls_time}s")
                self.force_keyframes = True
                if self.live:
                    HlsRelay._keyframe_urls.add(self.url)
                self._discard_primed_segments()
                # Nothing primed has been served, so the new encoder may
                # start on what the source already delivered.
                self._spawn_ffmpeg(replay=True)
                self._prime(m3u8, want)
        except BaseException:
            # Every exit from here leaks a server, its thread, an ffmpeg and
            # a temp directory if it does not tear them down itself.
            self.stop()
            raise
        # IPTV sources drop connections mid-stream (server reset, idle-timeout,
        # route flap). ffmpeg's reconnect flags cover reconnectable HTTP errors
        # but ffmpeg EXITS on a dead read; a supervisor restarts it in place so
        # the playlist keeps advancing and the receiver never notices.
        threading.Thread(target=self._supervise, daemon=True,
                         name="caster-relay-supervisor").start()
        self.play_url = f"http://{self._lan_ip()}:{self.port}/live.m3u8"
        return self.play_url

    def _live_target(self) -> int:
        """The EXT-X-TARGETDURATION a live relay advertises, at the least.

        A Cast receiver does not play a live playlist from where it is told
        to: it holds about three target durations behind the newest segment.
        Measured 2026-09-15 on RB Room with 2s segments and current_time=0,
        it jumped past the startup cushion and sat 0.1-6s behind the edge,
        so a feed a little under real time froze it every minute or two
        while the relay held 46s of history it never used.

        Advertising a third of the startup cushion puts that cushion where
        the receiver actually plays. Segments stay hls_time long -- EXTINF
        only has to be no longer than the target -- so keyframes, rotation
        and the retained window are untouched. A finite asset is not played
        at a live edge and keeps the encoder's own value.
        """
        if not self.live or not self.startup_seconds:
            return 0
        return max(self.hls_time, math.ceil(self.startup_seconds / 3))

    def _prime(self, m3u8: str, want: int) -> bool:
        """Wait until enough media exists for a receiver to accept the URL.

        Accumulate the HLS minimum and the chosen live startup cushion before
        handing out the URL. A longer history alone does not move Cast back
        from the live edge; the load also selects an explicit start position.
        The cushion is measured in seconds, not a count of source GOPs.
        A completed segment beyond
        GOP_COPY_LIMIT is enough evidence to restart with forced keyframes:
        waiting for two more long segments before making that decision was
        the direct cause of 30--60 second starts. Returns True only for that
        early-promotion case, otherwise False when the receiver's media
        requirement is met.
        """
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if os.path.exists(m3u8):
                completed = self._completed_segments()
                # A stream copy can cut only at the source's keyframes. One
                # completed over-limit segment therefore proves copying
                # cannot give the receiver prompt HLS segments. Re-encode
                # now, then prime three short segments, instead of collecting
                # three long ones merely to reach the same conclusion.
                if self._copy_gop_too_long():
                    return True
                # Three files are not necessarily three TARGETDURATIONs:
                # variable GOPs can yield (10s, 1s, 1s). Count only
                # published media and prime by duration as well.
                # HLS rounds EXTINF to the nearest integer, not upwards.
                # A normal 23.976/29.97fps segment is 2.002s: ceil made
                # three such segments wait for five (10s instead of 6s).
                target = max(1, int(max(completed.values(), default=0) + 0.5),
                             self._live_target())
                try:
                    with open(m3u8, encoding="utf-8") as playlist:
                        for line in playlist:
                            if line.startswith("#EXT-X-TARGETDURATION:"):
                                target = max(target, int(line.split(":", 1)[1]))
                                break
                except (OSError, ValueError):
                    pass
                if (len(completed) >= want
                        and sum(completed.values()) >= max(
                            3 * target, self.startup_seconds if self.live else 0)):
                    return False
            if self.proc is None:
                raise RuntimeError("relay stopped while starting")
            if self.proc.poll() is not None:
                if (not self.live and self.proc.returncode == 0
                        and self._completed_segments()):
                    return False    # a short file finished while priming
                raise RuntimeError(
                    "ffmpeg exited early while starting relay")
            # The supervisor starts AFTER priming. A throttled connection
            # used to wait out this entire 60s deadline with recovery off.
            # On the piped path recovery only swaps the upstream socket;
            # the encoder and the completed startup media survive it.
            if self.ts_source is not None:
                self._check_underfeed(time.monotonic())
            time.sleep(0.1)
        raise RuntimeError("relay produced no HLS playlist in time")

    def _copy_gop_too_long(self) -> bool:
        """Whether a stream copy cannot cut segments short enough to serve.

        Only meaningful about a copy: when the video is already being
        re-encoded the keyframes are ours to place, so there is nothing to
        detect and nothing to fix.
        """
        if self.video_transcoded or self.force_keyframes:
            return False
        completed = self._completed_segments()
        if not completed:
            return False
        return max(completed.values()) > self.GOP_COPY_LIMIT

    def _discard_primed_segments(self) -> None:
        """Throw away everything primed so far and start the numbering over.

        Only safe before the URL has been handed out. Re-encoded video does
        not continue the copied video's decoder configuration, so the two
        must not share a playlist; nothing has been served yet, so the
        cheapest correct answer is an empty directory rather than a seam.
        """
        prev = self.proc
        self.proc = None
        if prev is not None and prev.poll() is None:
            prev.kill()
            try:
                prev.wait(timeout=5)
            except Exception:
                prev.kill()
        try:
            for name in os.listdir(self.root):
                # `.tmp` too: hls_flags temp_file writes a segment beside its
                # final name and renames on completion, so a killed encoder
                # leaves one behind that the seg%05d.ts pattern does not see.
                if (re.fullmatch(r"seg(\d+)\.ts(\.tmp)?", name)
                        or name in ("live.m3u8", "live.m3u8.tmp")):
                    try:
                        os.remove(os.path.join(self.root, name))
                    except OSError:
                        pass
        except OSError:
            pass
        self._last_good = None
        self._trail_drop = None
        self._discont_segs.clear()

    def _newest_seg_number(self) -> int:
        """Highest segNNNNN.ts on disk, or -1 before the first one."""
        highest = -1
        try:
            for name in os.listdir(self.root):
                match = re.fullmatch(r"seg(\d+)\.ts", name)
                if match:
                    highest = max(highest, int(match.group(1)))
        except OSError:
            pass
        return highest

    def _next_segment_number(self) -> int:
        """The number a restarted encoder must resume from.

        Without this a restart begins again at seg00000, and the receiver --
        which has already played that name and may still be holding it -- is
        handed a file it believes it knows. What comes out of the speakers is
        audio from the start of the stream: playback jumps backwards.
        """
        return self._newest_seg_number() + 1

    def _spawn_ffmpeg(self, replay: bool = False) -> None:
        """(Re)start the ffmpeg encoder process for this relay.

        `replay` starts a piped encoder on the source's recent bytes; see
        TsSource.attach_with_replay for when that is safe.

        Kills any still-running previous encoder FIRST, so there is always
        exactly one ffmpeg per relay. Without this, _supervise's two-step
        read-self.proc-then-kill-proc races _spawn_ffmpeg's self.proc swap:
        the kill lands on the new process and the old one keeps running as a
        zombie -- the dual-ffmpeg state seen live on 2026-09-05.
        """
        if self.root is None:
            return          # stop() already tore down the temp directory
        # One encoder per relay, always.
        prev = self.proc
        self.proc = None
        if prev is not None and prev.poll() is None:
            prev.kill()
            try:
                prev.wait(timeout=5)
            except Exception:
                prev.kill()
        m3u8 = os.path.join(self.root, "live.m3u8")
        start = self._next_segment_number()
        # append_list marks the actual first new segment. Do not guess its
        # name from files on disk: an unfinished segment can be there too.
        cmd = self._ffmpeg_cmd(m3u8, start)
        # Keep stderr. ffmpeg says exactly why it is leaving -- a 456 from the
        # provider, a timed-out read, a codec it stopped being able to parse --
        # and DEVNULL threw that away, leaving only an exit code to reason
        # from. The pipe MUST be drained or a chatty encoder blocks on a full
        # buffer and stops producing segments, so the reader is not optional.
        tail: collections.deque = collections.deque(maxlen=self.STDERR_KEEP)
        self._stderr_tail = tail
        piped = self.piped_source()
        self.proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            stdin=subprocess.PIPE if piped else subprocess.DEVNULL,
            **_no_window_kwargs())
        threading.Thread(target=self._drain_stderr, args=(self.proc, tail),
                         daemon=True, name="caster-ffmpeg-stderr").start()
        if piped:
            # The reader outlives the encoder: it holds the tail that
            # recognises a replay, and losing it would replay one connection's
            # worth of the channel every time ffmpeg was replaced.
            if self._sink is None:
                self._sink = _Sink()
            if replay and self.ts_source is not None:
                self.ts_source.attach_with_replay(self.proc.stdin,
                                                  self.PRIME_REPLAY_BYTES)
            else:
                self._sink.attach(self.proc.stdin)
            if self.ts_source is None:
                self.ts_source = TsSource(self.url, self._sink)
                self.ts_source.start()
        # A (re)started encoder gets the benefit of the doubt: rotation is
        # judged only after it has had a chance to prove its cadence.
        self._proc_born = time.monotonic()
        self._fail_streak = 0
        self._eval_t0 = None

    @staticmethod
    def _drain_stderr(proc, tail) -> None:
        """Collect an encoder's diagnostics into its own bounded ring.

        The ring belongs to one process: a reader outliving its encoder must
        never append to the next one's tail and explain the wrong death.
        """
        stream = proc.stderr
        if stream is None:
            return
        try:
            for raw in stream:
                line = raw.decode("utf-8", "replace").strip()[:400]
                if line:
                    tail.append(_redact_urls(line))
        except (OSError, ValueError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    def encoder_last_words(self) -> str:
        """The tail of the last encoder's diagnostics, as one short line.

        ffmpeg repeats itself while a connection dies, so the useful part is
        the distinct ending, not the count.
        """
        seen = []
        for line in self._stderr_tail:
            if line not in seen:
                seen.append(line)
        return " | ".join(seen[-3:]) if seen else "no diagnostics"

    def _supervise(self) -> None:
        """Restart ffmpeg if it dies while the relay is up.

        A dead encoder freezes the playlist and the receiver eventually gives
        up ("stream disconnected"). Restarting in the same directory but continuing the
        segment numbering keeps the HLS continuity: names are never reused,
        the playlist is appended to rather than started over, and its
        MEDIA-SEQUENCE stays monotonic via trailing_playlist. The receiver
        just sees the stream continue.
        """
        while self.httpd is not None:
            time.sleep(2)
            if self.httpd is None:
                break   # stopped while sleeping
            now = time.monotonic()
            proc = self.proc
            if proc is not None and proc.poll() is not None:
                # ffmpeg exited on its own: upstream dropped and reconnect
                # flags gave up. Restart it unless we are shutting down.
                if self.httpd is None:
                    break
                if not self.live and proc.returncode == 0:
                    # A finite source simply ended. Restarting it replayed a
                    # local .m2ts from the start every two seconds, and the
                    # receiver sat in BUFFERING instead of finishing.
                    trace("relay.finished", "source ended; playlist closed")
                    break
                self._restarted += 1
                trace("relay.restart",
                      f"encoder exited with code {proc.returncode}: "
                      f"{self.encoder_last_words()}")
                try:
                    self._spawn_ffmpeg()
                except Exception:
                    pass
                continue
            if proc is not None:
                try:
                    self._check_gop()
                except Exception:
                    pass
                if self.proc is not proc:
                    continue    # _check_gop replaced the encoder
                try:
                    self._check_underfeed(now)
                except Exception:
                    pass

    def _check_gop(self) -> None:
        """Promote a copy to forced keyframes when the source stretches.

        start() already measures the GOP once, during priming, and re-encodes
        when a copy cannot cut segments short enough. That measurement is
        cheap and invisible, but it only ever sees the first few seconds of
        the channel -- and a source's keyframe spacing is not a constant.

        Measured on the Big Bang channel, 2026-09-09, casting to a real
        receiver: priming saw segments of 1.001s, 1.043s and 0.959s, so the
        copy was kept; a hundred seconds later the same encoder was writing
        3.003s, then 9.509s, and the Chromecast froze at a current_time that
        never moved again while the relay ran on healthily -- 0 restarts, 0
        upstream reconnects, every advertised segment present on disk. With
        -c copy a segment can only end on a keyframe, so a 9.5s segment IS a
        9.5s wait at the live edge. No playlist tuning shortens it, and the
        under-feed rotation cannot see it because the feed is not slow.

        So the same verdict start() reaches once is reached continuously.
        The switch costs an encoder restart, which on the piped path keeps
        the upstream connection (the sink is re-attached, no new socket to a
        provider that counts them) and is marked with a discontinuity the
        receiver already knows how to cross. One seam, once, against a stall
        every time the source's GOP stretches.
        """
        if self.video_transcoded or self.force_keyframes:
            return              # already placing our own keyframes
        if not self.live:
            return              # a finite asset is not worth re-encoding
        if not self._copy_gop_too_long():
            return
        longest = max(self._completed_segments().values())
        trace("relay.keyframes.promote",
              f"source segment reached {longest:.1f}s mid-stream (limit "
              f"{self.GOP_COPY_LIMIT:.0f}s); re-encoding to place keyframes "
              f"every {self.hls_time}s")
        self.force_keyframes = True
        HlsRelay._keyframe_urls.add(self.url)
        self._spawn_ffmpeg()    # picks the new flag up from _ffmpeg_cmd

    def _check_underfeed(self, now: float) -> None:
        """Rotate the source connection when a live encoder under-produces.

        ffmpeg does not drop on a throttled source: it keeps the connection
        and simply delivers packets slower than real time, so the relay's
        trail drains and the receiver stalls -- on a Chromecast a starved
        live HLS stream just sits there reporting PLAYING, which the app's
        reconnect watchdog never sees. Some IPTV CDNs cap throughput by
        connection age (hot at open, decaying after), so the cure is a fresh
        connection: kill this encoder and the supervisor's restart path
        brings one up in the same directory with continuing numbering.
        """
        if not self.live:
            return
        if not self.url.lower().startswith(("http://", "https://")):
            return
        # A socket swap is cheap and an encoder kill is not, so the two
        # paths do not get to rotate at the same cadence.
        piped = self.ts_source is not None
        min_age = self.ROTATE_MIN_AGE_PIPED if piped else self.ROTATE_MIN_AGE
        min_gap = self.ROTATE_MIN_GAP_PIPED if piped else self.ROTATE_MIN_GAP
        if now - self._proc_born < min_age:
            return
        if now - self._last_rotate < min_gap:
            return
        segments = self._completed_segments()
        if not segments:
            return
        newest = max(segments)
        if self._eval_t0 is None:
            # Open a cadence window: count segments from here for EVAL secs.
            self._eval_t0 = (now, newest)
            return
        t0, n0 = self._eval_t0
        span = now - t0
        # Segment publication is bursty: with stream-copy a long GOP can
        # leave a healthy encoder apparently idle between keyframes.
        if span < max(self.ROTATE_EVAL, 3 * max(segments.values())):
            return
        # Close the window and open the next one.
        self._eval_t0 = (now, newest)
        if min(segments) > n0 + 1:
            # The raw playlist rolled past this window. Its missing media
            # cannot be counted as zero (fast/short-GOP streams do this).
            self._fail_streak = 0
            return
        media = sum(duration for number, duration in segments.items()
                    if number > n0)
        # Media produced per wall-second.  Sum the actual EXTINF durations of
        # newly written segments rather than multiplying by the latest one:
        # source GOPs vary, and a long final segment otherwise makes a slow
        # connection look healthy (or a healthy one look starved).
        ratio = media / span
        if ratio >= (self.ROTATE_RATIO_PIPED if piped else self.ROTATE_RATIO):
            self._fail_streak = 0
            return
        self._fail_streak += 1
        if (ratio >= self.ROTATE_HARD_RATIO
                and self._fail_streak < self.ROTATE_STREAK):
            return
        # Sustained under-feed: rotate to a connection that opens hot.
        failed_windows = self._fail_streak
        self._last_rotate = now
        self._fail_streak = 0
        self._eval_t0 = None
        self._rotated += 1
        source = self.ts_source
        trace("relay.rotate",
              f"{ratio:.2f}x media for {failed_windows} consecutive "
              f"windows ({span:.1f}s last window); dropping the "
              f"{'source connection' if source else 'encoder'}")
        if source is not None:
            # On the piped path ffmpeg is not holding the socket, so killing
            # it would cost a restart and change nothing upstream. Drop the
            # connection itself; the reader opens the next one and the
            # encoder never notices.
            source.rotate()
            return
        try:
            self.proc.kill()
        except Exception:
            pass   # already gone; nothing to kill

    def _completed_segments(self) -> dict[int, float]:
        """Read completed segments from one atomic encoder playlist snapshot.

        Never use the newest file on disk as the cadence baseline: ffmpeg
        creates that file BEFORE finishing it. Doing so omits its eventual
        duration from every window and can rotate a healthy live connection.
        """
        if self.root is None:
            return {}
        try:
            with open(os.path.join(self.root, "live.m3u8"), "r",
                       encoding="utf-8", errors="replace") as f:
                dur = None
                segments = {}
                for line in f:
                    if line.startswith("#EXTINF:"):
                        try:
                            dur = float(line.split(":", 1)[1]
                                         .split(",", 1)[0])
                        except (ValueError, IndexError):
                            dur = None
                        continue
                    if not line.strip() or line.startswith("#"):
                        continue
                    name = re.fullmatch(r"seg(\d+)\.ts", line.strip())
                    if name and dur is not None and math.isfinite(dur) and dur > 0:
                        segments[int(name.group(1))] = dur
                    dur = None
                return segments
        except OSError:
            return {}

    def _ffmpeg_cmd(self, m3u8: str, start_number: int = 0) -> list:
        """ffmpeg command producing HLS for this relay's source."""
        append = start_number > 0
        if append:
            # append_list adds the old entry count to start_number. Passing
            # the next filename shifts the sequence of EVERY retained URI.
            # Continue from the existing playlist's base instead.
            try:
                with open(m3u8, encoding="utf-8") as playlist:
                    for line in playlist:
                        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                            start_number = int(line.split(":", 1)[1])
                            break
            except (OSError, ValueError):
                pass
        cmd = [_find_ffmpeg(), "-hide_banner", "-loglevel", "error"]
        piped = self.piped_source()
        if piped:
            # TsSource is doing the reading. Give the demuxer the format it
            # will get -- a pipe cannot be probed by seeking -- and set no
            # timeout of any kind: a quiet pipe is TsSource reconnecting, and
            # ffmpeg exiting through that would undo the whole point.
            #
            # thread_queue_size is the queue between the thread reading this
            # pipe and the muxer, and its default of 8 packets is sized for a
            # source that arrives evenly. These do not: one provider was
            # measured bursting to 131 Mb/s with gaps of up to 10.6s between
            # bursts while tracking real time exactly (see ROTATE_EVAL). A
            # burst that outruns an 8-packet queue is dropped input, which is
            # a hole in the TS rather than a delay. Raising it costs memory
            # and nothing else. It does NOT fix a starved CPU -- the copy
            # path has no such problem -- it fixes exactly the bursty
            # delivery this source is known for.
            cmd += ["-thread_queue_size", "4096", "-f", "mpegts"]
        elif self.url.lower().startswith(("http://", "https://")):
            # Survive IPTV sources dropping/jittering instead of stalling.
            # These belong to the HTTP protocol handler and nothing else:
            # handed a local path, ffmpeg refuses the whole command with
            # "Option reconnect not found" and opens no input at all.
            cmd += [
                # A live stream has no byte positions to come back to. Left
                # to itself ffmpeg reconnects with "Range: bytes=<offset>"
                # after every drop -- and this server drops every ten to
                # twenty seconds. -seekable 0 used to stop the Range request
                # and measured 0.89x here (2026-09-03); the server changed
                # (2026-09-05): it now IGNORES the unseekable declaration,
                # serves its own buffer from an earlier point, and ffmpeg
                # splices that in as though it followed on. Measured 5.2x
                # media per wall-second -- most of the channel arriving
                # twice, heard and seen as constant skip-backs.
                #
                # So: no reconnect flags at all. A drop makes ffmpeg EXIT,
                # and _supervise restarts it at the live edge in the same
                # directory -- the playlist stays monotonic, the receiver
                # rides through with a short freeze instead of a rewind.
                #
                # This branch is now only for playlist sources, which ffmpeg
                # has to fetch itself. A raw live stream goes down the piped
                # path instead (see TsSource), where the replay is removed
                # rather than ridden through.
                "-seekable", "0",
                "-rw_timeout", "5000000",   # 5s read timeout on the source
            ]
        # Inspect as little of the source as it takes to identify it. The
        # defaults spend five seconds on an MPEG-TS before writing anything,
        # and that is five seconds of nothing at the start of every channel.
        cmd += ["-analyzeduration", "1000000", "-probesize", "1000000"]
        cmd += [
            # An input flag: it fills in timestamps the source omits, so it
            # has to be set on the demuxer, before -i. After -i it lands on
            # the muxer, where it means nothing.
            "-fflags", "+genpts",         # smooth over source timestamp jumps
            "-i", "pipe:0" if piped else self.url,
        ]
        # Cast receivers play H.264-in-TS but reject anything else (HEVC,
        # AV1...). H.264 sources stay bit-exact; anything else gets the
        # video transcoded with the fastest hardware encoder available
        # while audio is copied untouched.
        codecs = self.codecs
        if codecs is None:
            codecs = _probe_codecs(self.url)
        bad_video = {"hevc", "h265", "av1", "mpeg2video", "mpeg4", "vp9",
                     "vp8", "theora", "wmv1", "wmv2", "wmv3", "vc1",
                     "msmpeg4v2", "msmpeg4v3", "mjpeg"}
        self.video_transcoded = any(c in bad_video for c in codecs)
        # Audio the receiver will not decode from a TS, or that MPEG-TS cannot
        # carry at all. Copied, it fails the whole relay; a local file's
        # sound can be anything a container allows.
        bad_audio = {"opus", "vorbis", "flac", "alac", "wmav1", "wmav2",
                     "wmapro", "pcm_s16le", "pcm_s24le", "dts", "truehd"}
        audio = (["-c:a", "aac", "-b:a", "192k"]
                 if any(c in bad_audio for c in codecs) else ["-c:a", "copy"])
        # Re-encoding buys the right to place keyframes. Whether we are here
        # because the codec is unplayable or because the source's keyframes
        # are too sparse to cut on, put one at every segment boundary: it
        # costs nothing extra once the encoder is already running, and an
        # HLS muxer left waiting for the encoder's own GOP writes nothing.
        transcode = self.video_transcoded or self.force_keyframes
        if transcode:
            cmd += ["-c:v", pick_h264_encoder(), *audio,
                    "-force_key_frames",
                    f"expr:gte(t,n_forced*{self.hls_time})"]
        elif audio[1] != "copy":
            cmd += ["-c:v", "copy", *audio]
        else:
            cmd += ["-c", "copy"]   # remux only: bit-exact, no quality loss
        # Put the H.264 parameter sets in front of every keyframe. An HLS
        # segment has to be decodable on its own -- a receiver may join at any
        # one of them -- and a live TS carries those sets only occasionally,
        # so without this the first segment of a channel can arrive describing
        # frames with nothing to describe them by. Costs a few bytes a
        # keyframe and nothing else.
        if not transcode:
            cmd += ["-bsf:v", "dump_extra=freq=keyframe"]
        cmd += [
            "-f", "hls",
            "-hls_time", str(self.hls_time),
            # Retained media is a DURATION, and counting segments hid that.
            # delete_segments removes anything older than this many entries,
            # so the window it keeps is list_size * segment length -- and the
            # segment length is not ours to assume. At a source's own 5-9s
            # GOP, 24 entries retained 120-216s behind a 45s cushion. Forcing
            # keyframes cut segments to hls_time (2s), and the same 24
            # entries retained 48s behind that same 45s cushion: the receiver
            # starts at the oldest segment it is shown, one hiccup puts the
            # file it needs next behind the delete, and a 404 there is a
            # permanent BUFFERING with the position frozen while the playlist
            # runs away from it -- observed on a receiver stuck at 41.8s
            # while the relay advanced to sequence 172.
            #
            # Keep at least twice the cushion, plus a margin, so falling
            # behind costs a rebuffer and not the stream.
            "-hls_list_size", str(self._list_size()),
            # Leaving the playlist and leaving the disk are two different
            # moments, and the default collapses them: hls_delete_threshold
            # is 1, so a segment file is unlinked one segment after its URI
            # stops being advertised. The receiver starts at the OLDEST
            # segment it is shown, which puts it one slip away from asking
            # for a file that no longer exists -- and a 404 there is not a
            # rebuffer but the permanent freeze recorded in AGENTS.md, the
            # receiver stuck at 41.8s while the playlist ran to sequence 172.
            #
            # RFC 8216 6.2.2 asks for exactly this margin: a removed segment
            # SHOULD stay fetchable for its own duration plus the duration of
            # the longest playlist served, so retention wants to be about
            # twice the advertised window. hls_list_size buys that by
            # ADVERTISING more, which also moves where a receiver starts and
            # how it reads the live edge; this buys it on disk alone, where
            # it costs nothing a receiver can see. One cushion's worth of
            # already-dropped segments, floored so a short window still gets
            # a usable grace.
            "-hls_delete_threshold", str(self._delete_threshold()),
            # append_list continues the existing playlist across a restart
            # instead of truncating it, which would strip the segments the
            # receiver is still working through.
            #
            # temp_file writes each segment and each playlist rewrite to a
            # neighbouring .tmp and renames it into place, so nothing served
            # over the HTTP hop is ever half-written. _completed_segments
            # already notes that ffmpeg creates a segment file before it
            # finishes it; this makes the file appear only once it is whole.
            #
            # NO program_date_time, and the reason is the whole design here.
            # Google's Web Receiver docs say a refreshed live manifest is
            # merged on #EXT-X-PROGRAM-DATE-TIME when present and only falls
            # back to #EXT-X-MEDIA-SEQUENCE otherwise, which reads like an
            # argument for adding it: the sequence number is the fragile half
            # of that pair, which is why _served_seq has to ratchet it.
            #
            # The argument against is that the ratchet is not a workaround
            # for a weak anchor, it IS the anchor: _trailing_playlist rewrites
            # the sequence so that whatever a restarted encoder does to its
            # own numbering, what leaves here never goes backwards. PDT is
            # passed through from ffmpeg untouched, so adding it would hand
            # the receiver a second timeline that the rewrite does not govern
            # -- and by Google's own description the receiver would prefer
            # that one over the rewritten sequence.
            #
            # That is reasoning, not a measurement. It was tried against a
            # real receiver on 2026-09-09 and the attempt produced no usable
            # verdict: over four 360s casts of one channel to RB Room the
            # SAME code scored 145/180 samples PLAYING on one run and 2/180
            # on another, because the upstream channel degraded across the
            # session (by the end it was being served at 0.41x with segments
            # up to 10.4s). Run-to-run variance swamped the change, in both
            # directions, so nothing was learned about PDT either way.
            #
            # It stays out on the burden of proof: it is an unproven addition
            # to the one part of the playlist this class rewrites most
            # carefully. Anyone revisiting it needs a source that holds still
            # long enough to measure, not this one.
            "-hls_flags",
            ("delete_segments+temp_file+append_list"
             if append else
             "delete_segments+temp_file"),
            "-start_number", str(start_number),
            "-hls_segment_filename", os.path.join(self.root, "seg%05d.ts"),
            m3u8,
        ]
        return cmd

    def _list_size(self) -> int:
        """How many segments ffmpeg retains, sized by the media they hold.

        The floor is the cushion the receiver is deliberately held behind,
        doubled and then padded: it has to survive falling behind, not merely
        start correctly.
        """
        cushion = max(self.trail_seconds, 3 * self.hls_time,
                      self.trail_keep * self.hls_time)
        wanted = math.ceil((cushion * 2 + 30) / max(1, self.hls_time))
        return max(24, self.trail_keep * 3, wanted)

    def _delete_threshold(self) -> int:
        """Segments kept on disk after their URI leaves the playlist.

        The grace a receiver gets to finish fetching something it was shown
        a moment ago. ffmpeg's default is 1 segment, which is no grace at
        all for a receiver sitting at the oldest advertised URI.

        Sized in seconds like everything else here, because a count is
        meaningless while the segment length belongs to the source's GOP: one
        cushion's worth, so a receiver may fall a whole cushion behind the
        oldest thing it was offered and still be served. Floored at 15 so a
        short cushion still leaves a usable margin, and it costs only disk --
        at 2s segments and a 45s cushion this is ~23 files that no longer
        appear in any playlist.
        """
        seconds = max(self.trail_seconds, self.trail_keep * self.hls_time,
                      3 * self.hls_time)
        return max(15, math.ceil(seconds / max(1, self.hls_time)))

    def trailing_playlist(self):
        # Concurrent HTTP polls must see a consistent timeline.
        with self._playlist_lock:
            return self._trailing_playlist()

    def _trailing_playlist(self):
        """A sliding history window, with duration and sequence safeguards.

        Keeping history alone does not select the receiver's play position.
        Returns None before a usable playlist exists.
        """
        if not self.root:
            return None   # relay already stopped; straggler request
        p = os.path.join(self.root, "live.m3u8")
        try:
            with open(p, "rb") as f:
                raw = f.read()
            if len(raw) < 20 or not raw.startswith(b"#EXTM3U"):
                raise OSError("partial playlist")
            self._last_good = raw
        except OSError:
            raw = self._last_good
            if raw is None:
                return None
        lines = raw.decode("utf-8", "replace").splitlines()
        try:
            seq_idx = next(i for i, l in enumerate(lines)
                           if l.startswith("#EXT-X-MEDIA-SEQUENCE:"))
            base_seq = int(lines[seq_idx].split(":", 1)[1])
        except (StopIteration, ValueError):
            return None
        segs = [i for i, l in enumerate(lines) if l and not l.startswith("#")]
        if not segs:
            return None
        drop = max(0, len(segs) - self.trail_keep)
        # Keep enough actual media, in seconds. Two floors apply: the cast
        # receiver refuses to start below 3x TARGETDURATION, and this source
        # delivers in bursts, so the cushion has to outlast the longest quiet
        # spell between them or the receiver reaches the end and rebuffers.
        try:
            target = max(self._served_target or 0, self._live_target(), float(next(
                l.split(":", 1)[1] for l in lines
                if l.startswith("#EXT-X-TARGETDURATION:"))))
            durations = [float(l.split(":", 1)[1].rstrip(",")) for l in lines
                         if l.startswith("#EXTINF:")]
            if len(durations) == len(segs):
                want = max(3 * target, self.trail_seconds)
                total = sum(durations[drop:])
                while drop > 0 and total < want:
                    drop -= 1
                    total += durations[drop]
        except (ValueError, StopIteration):
            pass
        # A larger cushion must grow forwards; never resurrect segments the
        # receiver has already scrolled past. A relative-drop high-water mark
        # would prevent that growth even while the raw base advances.
        if self._served_seq is not None:
            drop = max(drop, self._served_seq - base_seq)
        drop = min(drop, len(segs) - 1)
        self._trail_drop = drop

        def block_start(uri_idx: int) -> int:
            # Index of the first comment line belonging to this segment's
            # block (typically its EXTINF), stopping at the previous URI.
            j = uri_idx
            while j - 1 > seq_idx and lines[j - 1].startswith("#"):
                j -= 1
            return j

        header_end = block_start(segs[0])   # comments after MEDIA-SEQUENCE
        # append_list already marks restart seams. Record before trimming.
        for uri_idx in segs:
            num = re.fullmatch(r"seg(\d+)\.ts", lines[uri_idx].strip())
            if num and "#EXT-X-DISCONTINUITY" in lines[block_start(uri_idx):uri_idx]:
                self._discont_segs.add(int(num.group(1)))
        # The ratchet. A restarted encoder numbers from wherever it likes, and
        # handing the receiver a sequence lower than one it has already seen
        # tells it to play those segments again -- heard as the stream jumping
        # backwards. Serving a short playlist raw did exactly that, which is
        # why this rewrite now happens for every playlist, not only long ones.
        seq = base_seq + drop
        if self._served_seq is not None and seq < self._served_seq:
            seq = self._served_seq
        self._served_seq = seq

        # Restart seams. A segment written by a NEW encoder connection does
        # not continue the previous one's timestamp clock, so it is preceded
        # by a DISCONTINUITY tag -- the receiver then re-initialises its
        # decoder at the seam instead of splicing the two timelines, which
        # played the last few seconds twice and then failed.
        # RFC 8216 4.3.3.1: EXT-X-TARGETDURATION must not change between
        # reloads of a live playlist. ffmpeg recomputes it from whatever is
        # in its own window, so a source with an irregular GOP makes it
        # oscillate: measured 10 -> 6 -> 10 on one channel whose keyframes
        # ran 1.0s to 7.7s apart, 27% of them over 4s. A player sizes its
        # buffer and its live-edge start distance from this number, and
        # handing it a smaller one than it has already acted on invites the
        # rebuffer it is meant to prevent. Ratchet it: never decrease. It
        # must still be free to GROW, because an EXTINF longer than
        # TARGETDURATION is a violation in the other direction.
        #
        # ffmpeg writes it ahead of MEDIA-SEQUENCE, so it arrives in the
        # prefix below rather than the header slice further down; apply the
        # ratchet to both so the layout is not load-bearing.
        def target_ratchet(line: str) -> str:
            if not line.startswith("#EXT-X-TARGETDURATION:"):
                return line
            try:
                value = int(float(line.split(":", 1)[1]))
            except ValueError:
                return line
            value = max(value, self._live_target())
            if self._served_target is not None:
                value = max(value, self._served_target)
            self._served_target = value
            return f"#EXT-X-TARGETDURATION:{value}"

        out = [target_ratchet(line) for line in lines[:seq_idx]
               if not line.startswith("#EXT-X-DISCONTINUITY-SEQUENCE:")]
        out.append(f"#EXT-X-MEDIA-SEQUENCE:{seq}")
        first = re.fullmatch(r"seg(\d+)\.ts", lines[segs[drop]].strip())
        if first and self._discont_segs:
            # Preserve timeline IDs when a restart seam leaves the window.
            count = sum(n < int(first.group(1)) for n in self._discont_segs)
            out.append(f"#EXT-X-DISCONTINUITY-SEQUENCE:{count}")
        out.extend(target_ratchet(line)
                   for line in lines[seq_idx + 1:header_end])
        for uri_idx in segs[drop:]:
            num = re.fullmatch(r"seg(\d+)\.ts", lines[uri_idx].strip())
            if num and int(num.group(1)) in self._discont_segs:
                out.append("#EXT-X-DISCONTINUITY")
            out.extend(line for line in lines[block_start(uri_idx):uri_idx + 1]
                       if line != "#EXT-X-DISCONTINUITY")
        # ffmpeg closes a finished source with ENDLIST after the last URI,
        # outside every block copied above. Dropped, a receiver never learns
        # the file ended and waits at the edge for a segment that never comes.
        if "#EXT-X-ENDLIST" in lines[segs[-1]:]:
            out.append("#EXT-X-ENDLIST")
        return ("\n".join(out) + "\n").encode("utf-8")

    @staticmethod
    def _lan_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()

    def stop(self) -> None:
        # Tear the supervisor's loop condition down FIRST: httpd=None makes
        # _supervise exit, so it never restarts a relay being torn down.
        httpd, self.httpd = self.httpd, None
        # Stop reading the source before killing the encoder it feeds, or the
        # reader spends its next write on a pipe that has just gone.
        source, self.ts_source = self.ts_source, None
        if source is not None:
            source.stop()
        if self._sink is not None:
            self._sink.attach(None)
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        if httpd:
            # Without these the port stays bound and the serving thread stays
            # alive for the life of the app, once per relay. shutdown() waits
            # for serve_forever to notice, and stop() is called from the UI
            # thread, so it goes on a thread of its own.
            threading.Thread(target=httpd.shutdown, daemon=True).start()
            httpd.server_close()
        if self.root:
            shutil.rmtree(self.root, ignore_errors=True)
        self.root = None
        self.play_url = None


class SeekablePipeReader(io.BufferedIOBase):
    """A forward-only byte stream that pyatv can open.

    pyatv 0.17 with miniaudio 1.61 cannot decode a stream it cannot seek.
    Measured offline, the same WAV bytes decode from a BytesIO in 0.03 s and
    fail with DecodeError -17 (MA_AT_END) from a non-seekable reader or an
    asyncio.StreamReader. That was every AirPlay path except a local file:
    the ffmpeg pipe for video and IPTV, audio URLs, YouTube and system audio.

    So the start of the stream, which the decoder and pyatv's metadata parse
    both rewind to, is kept for good, along with a window behind the read
    position. A seek past what has arrived stops at what has arrived: pulling
    a live source forward to answer a probe for its end would never return.

    The source is read directly, never through the event loop. The old reader
    bounced each read through run_coroutine_threadsafe, and pyatv parses
    metadata ON the loop thread, so that read waited on itself for its whole
    30 s timeout and the receiver never switched input.
    """

    HEAD = 256 << 10        # kept for the life of the stream
    BEHIND = 1 << 20        # kept behind the read position
    CHUNK = 64 << 10

    def __init__(self, read, close=None) -> None:
        super().__init__()
        self._source_read = read      # blocking (n) -> bytes, b"" at the end
        self._source_close = close
        self._head = bytearray()
        self._buf = bytearray()
        self._base = 0                # absolute offset of _buf[0]
        self._pos = 0
        self._eof = False

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def _available(self) -> int:
        return self._base + len(self._buf)

    def _fill(self, upto: int) -> None:
        while not self._eof and self._available() < upto:
            chunk = self._source_read(self.CHUNK)
            if not chunk:
                self._eof = True
                break
            if len(self._head) < self.HEAD:
                self._head += chunk[:self.HEAD - len(self._head)]
            self._buf += chunk

    def prefill(self, size: int = CHUNK) -> None:
        """Pull the start of the stream in now, off the event loop."""
        self._fill(size)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.CHUNK
        if self._pos > self._available() + self.BEHIND:
            return b""                # parked by a far seek; see seek()
        if self._pos < self._base:
            if self._pos < len(self._head):
                end = min(len(self._head), self._pos + size)
                data = bytes(self._head[self._pos:end])
                self._pos = end
                return data
            self._pos = self._base    # that span is gone; resume at what is kept
        self._fill(self._pos + size)
        start = self._pos - self._base
        data = bytes(self._buf[start:start + size])
        self._pos += len(data)
        drop = self._pos - self._base - self.BEHIND
        if drop > 0:
            del self._buf[:drop]
            self._base += drop
        return data

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        if whence == io.SEEK_CUR:
            target = self._pos + offset
        elif whence == io.SEEK_END:
            target = self._available()
        else:
            target = offset
        if target - self._available() > self.BEHIND:
            # Far past anything that has arrived. ffmpeg writes a pipe WAV's
            # sizes as 0xFFFFFFFF, so pyatv's metadata parse skips the data
            # chunk by that, then reads samples as chunk sizes and seeks by
            # them. Clamping each seek and reading on walked the whole stream
            # -- forever on a live one, on the event loop -- and the trimmed
            # window then cost all but 1.31 MB of a 4.4 MB file. Park there
            # without pulling; a read from here returns nothing, ending the
            # walk, and the parse seeks back to where it began.
            self._pos = target
            return self._pos
        if 0 < target - self._available() <= self.BEHIND:
            self._fill(target)        # a short skip ahead, e.g. past a chunk
        target = max(0, min(target, self._available()))
        if len(self._head) <= target < self._base:
            target = self._base
        self._pos = target
        return self._pos

    def close(self) -> None:
        closer, self._source_close = self._source_close, None
        if closer is not None:
            try:
                closer()
            except Exception:
                pass
        super().close()


class HlsFileHandler(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive: fewer TCP handshakes

    #: Diagnostic record of recent fetches. Bounded: a long IPTV cast fetches
    #: a segment every couple of seconds for hours, and an unbounded list of
    #: them is a slow leak for something only ever read while debugging.
    relay_requests = collections.deque(maxlen=200)

    _TYPES = {
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
        ".m4s": "video/iso.segment",
        ".mp4": "video/mp4",
    }

    def guess_type(self, path):
        # Windows' mimetypes registry maps .ts to TypeScript and .m3u8 to
        # random things; receivers reject those, so force the right types.
        import os as _os
        return self._TYPES.get(_os.path.splitext(path)[1].lower(),
                               "application/octet-stream")

    def end_headers(self):
        # Some cast receivers (esp. FFM-based TVs) refuse HLS without CORS
        # headers, even though the fetch is native. Send permissive ones.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _serve_playlist(self, send_body: bool) -> bool:
        """Serve the relay's current playlist for GET or HEAD.

        Chromecast's media stack can probe a playlist with HEAD before it
        starts its normal GET/poll loop.  A HEAD response has to carry the
        same headers as GET but *no body*: writing playlist bytes there puts
        unexpected bytes into the persistent HTTP/1.1 connection, so the
        next parser can mistake them for the beginning of another response.
        """
        path_only = self.path.split("?")[0]
        if not path_only.rstrip("/").endswith("live.m3u8") or self.server is None:
            return False
        relay = getattr(self.server, "relay", None)
        if relay is None:
            return False
        data = relay.trailing_playlist()
        if data is None:
            return False
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.apple.mpegurl")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if send_body:
            self.wfile.write(data)
        return True

    def do_GET(self):
        HlsFileHandler.relay_requests.append(
            (time.strftime("%H:%M:%S"), self.path, self.client_address[0]))
        # Playlist requests get the trailing-edge view (see HlsRelay).
        # Strip query string: a receiver appending ?_=N must still match.
        if self._serve_playlist(send_body=True):
            return
        return super().do_GET()

    def do_HEAD(self):
        # HEAD has the same representation headers as GET, but RFC 9110
        # forbids a response body.  In particular, do not delegate to
        # do_GET(): this handler deliberately uses persistent connections.
        if self._serve_playlist(send_body=False):
            return
        return super().do_HEAD()

    def log_message(self, format, *args):
        pass  # keep console quiet


class LoopThread(threading.Thread):
    """Daemon thread owning the asyncio loop for pyatv."""

    def __init__(self) -> None:
        super().__init__(daemon=True, name="caster-asyncio")
        self.loop = asyncio.new_event_loop()
        self.ready = threading.Event()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.ready.set()
        self.loop.run_forever()

    def submit(self, coro) -> concurrent.futures.Future:
        """Run a coroutine on the loop and hand back its future.

        Returning it matters: the caller cancels through it on stop and waits
        on it while closing. Dropping it made both no-ops -- the AirPlay
        runner was never cancelled and never waited for, so the app exited
        without letting the receiver tear the session down.
        """
        return asyncio.run_coroutine_threadsafe(coro, self.loop)


#: How each receiver kind is shown in the device list.
KIND_LABELS = {
    "chromecast": "Cast",
    "airplay": "AirPlay",
    "upnp": "UPnP",
    "sonos": "Sonos",
    "roku": "Roku",
    "kodi": "Kodi",
    "musiccast": "MusicCast zone",
}

#: Receivers that can show a picture. Sonos is speakers, and AirPlay here is
#: RAOP, which carries audio only -- pyatv cannot mirror a screen.
VIDEO_KINDS = {"chromecast", "upnp", "roku", "kodi"}


class Device:
    def __init__(self, kind: str, name: str, key: Any,
                 sinks: frozenset = frozenset()) -> None:
        self.kind = kind          # a key of KIND_LABELS
        self.name = name
        self.key = key
        #: Content types the receiver said it accepts, empty when it did not
        #: say. See Device.supports_video.
        self.sinks = sinks
        #: {"host", "zone"} when this device also answers MusicCast, which is
        #: a control channel rather than a transport -- see caster_devices.
        self.musiccast: Optional[dict] = None

    @property
    def host(self) -> str:
        """The device's address, however its protocol happens to record it."""
        key = self.key
        if isinstance(key, dict):
            if key.get("host"):
                return str(key["host"])
            if key.get("ip"):
                return str(key["ip"])
            for field in ("control_url", "base"):
                if key.get(field):
                    return upnp_host(str(key[field]))
            return ""
        return str(getattr(key, "address", "") or "")

    @property
    def supports_video(self) -> bool:
        """Whether sending this device a picture is worth doing.

        A renderer that published its accepted content types has answered
        this outright, and is believed: "UPnP renderer" covers televisions
        and stereo amplifiers alike, and encoding H.264 for an amplifier
        costs a whole encoder to produce something it will refuse. Silence
        falls back to the kind, because plenty of renderers answer
        GetProtocolInfo badly or not at all.
        """
        if self.sinks:
            return any(m.startswith("video/") for m in self.sinks)
        return self.kind in VIDEO_KINDS

    @property
    def label(self) -> str:
        return f"{self.name} ({KIND_LABELS.get(self.kind, self.kind)})"

    def __repr__(self) -> str:
        return f"Device({self.kind}, {self.name!r})"


async def _cancel(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass


async def _close_atv(atv) -> None:
    try:
        await asyncio.gather(*atv.close())
    except Exception:
        pass


async def _set_atv_volume(atv, level: float) -> None:
    try:
        await atv.audio.set_volume(level)
    except Exception:
        pass
