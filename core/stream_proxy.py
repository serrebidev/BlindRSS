# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

# core/stream_proxy.py
#
# Lightweight HTTP proxy and local file server used by BlindRSS for:
# - Forwarding required HTTP headers to upstream media URLs.
# - Forwarding Range requests (required for many Chromecast / smart TV receivers).
# - Remuxing MPEG-TS to HLS via ffmpeg for Chromecast compatibility.
# - Serving local files to network devices (Chromecast) with Range support.
#
# NOTE: This server is intended to be reachable both from localhost (VLC) and
# from LAN devices (Chromecast). It binds to 0.0.0.0 but will generate URLs
# using 127.0.0.1 for local clients unless a device_ip is provided.

import base64
import hashlib
import hmac
import http.server
import json
import logging
import mimetypes
import os
import shutil
import secrets
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from typing import Dict, Optional, Tuple

LOG = logging.getLogger(__name__)

# Ensure common audio types resolve correctly on Windows.
mimetypes.add_type("audio/mpeg", ".mp3")
mimetypes.add_type("audio/aac", ".aac")
mimetypes.add_type("audio/aac", ".m4a")
mimetypes.add_type("audio/ogg", ".ogg")
mimetypes.add_type("audio/ogg", ".oga")
mimetypes.add_type("audio/opus", ".opus")
mimetypes.add_type("audio/flac", ".flac")
mimetypes.add_type("audio/wav", ".wav")
mimetypes.add_type("video/mp2t", ".ts")
mimetypes.add_type("application/vnd.apple.mpegurl", ".m3u8")


_HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _safe_b64decode(s: str) -> bytes:
    # Add padding if needed
    pad = '=' * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("utf-8"))


def _safe_b64encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("utf-8").rstrip("=")


def _parse_range(range_header: str, size: int) -> Optional[Tuple[int, int]]:
    """
    Parse a single HTTP Range header like:
      Range: bytes=0-1023
      Range: bytes=1024-
      Range: bytes=-1024
    Returns (start, end) inclusive. None if invalid/unsupported.
    """
    if not range_header:
        return None
    rh = range_header.strip().lower()
    if not rh.startswith("bytes="):
        return None
    spec = rh[6:].strip()
    if "," in spec:
        # Multi-range not supported
        return None
    if "-" not in spec:
        return None
    a, b = spec.split("-", 1)
    a = a.strip()
    b = b.strip()

    if a == "" and b == "":
        return None

    if a == "":
        # suffix length: -N (last N bytes)
        try:
            n = int(b)
        except ValueError:
            return None
        if n <= 0:
            return None
        if n >= size:
            return (0, size - 1)
        return (size - n, size - 1)

    try:
        start = int(a)
    except ValueError:
        return None

    if start < 0:
        return None

    if b == "":
        end = size - 1
    else:
        try:
            end = int(b)
        except ValueError:
            return None

    if start >= size:
        return None
    if end < start:
        return None
    if end >= size:
        end = size - 1
    return (start, end)


class _QuietThreadingTCPServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 256

    def handle_error(self, request, client_address):
        # Clients often abort local HTTP connections during seek/stop.
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


class HLSConverter:
    def __init__(self, source_url, headers=None):
        """Helper that remuxes a source URL to local HLS for Chromecast.

        Some IPTV providers require additional HTTP headers (cookies, referer,
        authorization, etc.) for the stream to remain valid. When we transcode
        MPEG-TS to HLS for Chromecast, ffmpeg must send those headers too or
        the remote server may drop the connection shortly after start. To
        handle this, we keep the full headers dict and forward it via ffmpeg's
        -headers option in addition to an explicit -user_agent when present.
        """
        self.source_url = source_url
        self.headers = headers or {}
        self.user_agent = (
            self.headers.get("User-Agent")
            or self.headers.get("user-agent")
        )
        self.temp_dir = tempfile.mkdtemp(prefix="iptv_remux_")
        self.playlist_path = os.path.join(self.temp_dir, "stream.m3u8")
        self.process = None
        self.last_access = time.time()

        self._playlist_ready_event = threading.Event()
        self._monitor_thread = None

        self.start()

    def start(self):
        # -re is NOT used because we want to fill buffer fast; the upstream
        # server or network will naturally limit the effective rate.
        # -c copy keeps CPU usage low by avoiding re-encoding.
        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
        ]

        # Forward headers that some providers require (cookies, referer, auth, etc.)
        # in addition to a dedicated -user_agent option.
        if self.user_agent:
            cmd.extend(["-user_agent", self.user_agent])

        if self.headers:
            try:
                header_lines = []
                for k, v in self.headers.items():
                    if v is None:
                        continue
                    if k == "_extra":
                        continue
                    header_lines.append(f"{k}: {v}")
                if header_lines:
                    cmd.extend(["-headers", "\r\n".join(header_lines) + "\r\n"])
            except Exception:
                pass

        cmd.extend([
            "-i", self.source_url,
            "-c", "copy",
            "-f", "hls",
            "-hls_time", "4",
            "-hls_list_size", "20",
            "-hls_flags", "delete_segments+split_by_time",
            "-hls_segment_filename", os.path.join(self.temp_dir, "seg_%03d.ts"),
            self.playlist_path,
        ])

        LOG.info("Starting ffmpeg remux to %s", self.temp_dir)

        if not shutil.which("ffmpeg"):
            LOG.error("ffmpeg not found in PATH. Transcoding impossible.")
            return

        import platform
        creation_flags = 0
        startupinfo = None
        if platform.system().lower() == "windows":
            creation_flags = 0x08000000 # CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0 # SW_HIDE

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=creation_flags,
                startupinfo=startupinfo
            )
        except Exception as e:
            LOG.error("Failed to start ffmpeg: %s", e)
            self.process = None
            return

        # Monitor playlist creation so /transcode/<id>/stream.m3u8 can block briefly
        def monitor():
            try:
                deadline = time.time() + 15
                while time.time() < deadline:
                    if os.path.exists(self.playlist_path) and os.path.getsize(self.playlist_path) > 0:
                        self._playlist_ready_event.set()
                        return
                    time.sleep(0.2)
            finally:
                # Even on failure, set so waiters can return
                self._playlist_ready_event.set()

        self._monitor_thread = threading.Thread(target=monitor, daemon=True)
        self._monitor_thread.start()

    def stop(self):
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        except Exception as e:
            LOG.warning(f"Failed to terminate ffmpeg process: {e}")
        try:
            if self.process:
                self.process.wait(timeout=3)
        except Exception as e:
            LOG.warning(f"Error waiting for ffmpeg process: {e}")
            try:
                self.process.kill()
            except Exception as k:
                LOG.warning(f"Failed to kill ffmpeg process: {k}")

        self.process = None
        try:
            shutil.rmtree(self.temp_dir)
        except Exception as e:
            LOG.warning("Failed to cleanup temp dir %s: %s", self.temp_dir, e)

    def is_alive(self):
        return self.process and self.process.poll() is None

    def touch(self):
        self.last_access = time.time()

    def wait_for_playlist(self, timeout=15):
        # Block until the monitor thread has had a chance to create playlist
        self._playlist_ready_event.wait(timeout=timeout)
        return os.path.exists(self.playlist_path) and os.path.getsize(self.playlist_path) > 0


class StreamProxyHandler(http.server.BaseHTTPRequestHandler):
    # Chromecast / smart TVs are happier with HTTP/1.1, and they frequently use
    # HEAD + Range.
    protocol_version = "HTTP/1.1"

    def _authorized(self, path: str, query_string: str) -> bool:
        """Require the unguessable capability embedded in every generated URL."""
        try:
            supplied = str(path or "").lstrip("/").split("/", 1)[0]
            if not supplied:
                supplied = (urllib.parse.parse_qs(query_string).get("token") or [""])[0]
            expected = str(getattr(self.server, "proxy_token", "") or "")
            return bool(expected and supplied and hmac.compare_digest(str(supplied), expected))
        except Exception:
            return False

    def _reject_unauthorized(self) -> None:
        self.send_response(403)
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_OPTIONS(self):
        parsed = urllib.parse.urlparse(self.path)
        if not self._authorized(parsed.path, parsed.query):
            self._reject_unauthorized()
            return
        # CORS preflight support (harmless for media fetchers).
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,HEAD,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_HEAD(self):
        self._handle_request(send_body=False)

    def do_GET(self):
        self._handle_request(send_body=True)

    def _handle_request(self, send_body: bool):
        parsed = urllib.parse.urlparse(self.path)

        # The server is reachable from the LAN for casting. Treat its random token
        # as a capability so another machine cannot use /proxy as an open proxy or
        # /file as an arbitrary local-file reader merely by discovering the port.
        if not self._authorized(parsed.path, parsed.query):
            self._reject_unauthorized()
            return
        token_prefix = "/" + str(getattr(self.server, "proxy_token", "") or "")
        route_path = parsed.path[len(token_prefix):] if parsed.path.startswith(token_prefix) else parsed.path

        # --- Route: /transcode/<session_id>/<filename> ---
        if route_path.startswith("/transcode/"):
            return self._serve_transcode(route_path, send_body)

        # --- Route: /file ---
        if route_path == "/file":
            return self._serve_local_file(parsed.query, send_body)

        # --- Route: /proxy ---
        if route_path == "/proxy":
            return self._serve_proxy(parsed.query, send_body)

        self.send_error(404, "Not Found")

    def _serve_transcode(self, path: str, send_body: bool):
        parts = path.split("/")
        if len(parts) < 4:
            self.send_error(400, "Invalid transcode path")
            return

        session_id = parts[2]
        filename = parts[3]

        converter = get_proxy().get_converter(session_id)
        if not converter:
            self.send_error(404, "Session expired or not found")
            return

        converter.touch()

        if filename == "stream.m3u8":
            if not converter.wait_for_playlist():
                self.send_error(503, "Playlist generation failed or timed out")
                return
            file_path = converter.playlist_path
            content_type = "application/vnd.apple.mpegurl"
        else:
            file_path = os.path.join(converter.temp_dir, filename)
            content_type = "video/mp2t"

        if not os.path.exists(file_path):
            self.send_error(404, "File not found")
            return

        try:
            size = os.path.getsize(file_path)
            r = _parse_range(self.headers.get("Range", ""), size)

            if r:
                start, end = r
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
            else:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(size))

            self.send_header("Access-Control-Allow-Origin", "*")
            if filename.endswith(".m3u8"):
                self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
            self.send_header("Connection", "close")
            self.end_headers()

            if not send_body:
                return

            with open(file_path, "rb") as f:
                if r:
                    f.seek(start)
                    to_send = length
                else:
                    to_send = size

                while to_send > 0:
                    chunk = f.read(min(128 * 1024, to_send))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    to_send -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:
            LOG.error("Error serving transcode file: %s", e)
            try:
                self.send_error(500, "Internal server error")
            except Exception:
                pass

    def _serve_local_file(self, query_str: str, send_body: bool):
        query = urllib.parse.parse_qs(query_str)
        b64_path = query.get("path", [None])[0]
        if not b64_path:
            self.send_error(400, "Missing path parameter")
            return

        try:
            file_path = _safe_b64decode(b64_path).decode("utf-8", errors="strict")
        except Exception:
            self.send_error(400, "Invalid path parameter")
            return

        if not os.path.isfile(file_path):
            self.send_error(404, "File not found")
            return

        try:
            size = os.path.getsize(file_path)
            ctype, _ = mimetypes.guess_type(file_path)
            content_type = ctype or "application/octet-stream"

            r = _parse_range(self.headers.get("Range", ""), size)
            if r:
                start, end = r
                length = end - start + 1
                self.send_response(206)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
            else:
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(size))

            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Connection", "close")
            self.end_headers()

            if not send_body:
                return

            with open(file_path, "rb") as f:
                if r:
                    f.seek(start)
                    to_send = length
                else:
                    to_send = size

                while to_send > 0:
                    chunk = f.read(min(256 * 1024, to_send))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    to_send -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception as e:
            LOG.error("Local file serve error: %s", e)
            try:
                self.send_error(500, "Internal server error")
            except Exception:
                pass

    def _serve_proxy(self, query_str: str, send_body: bool):
        query = urllib.parse.parse_qs(query_str)
        target_url = query.get("url", [None])[0]
        if not target_url:
            self.send_error(400, "Missing url parameter")
            return

        # Reconstruct headers from query, then merge in important request headers
        req_headers: Dict[str, str] = {}
        headers_json = query.get("headers", [None])[0]
        if headers_json:
            try:
                decoded = base64.b64decode(headers_json).decode("utf-8")
                req_headers = json.loads(decoded) or {}
            except Exception as e:
                LOG.warning("Failed to decode headers: %s", e)
                req_headers = {}

        # Forward Range from the Chromecast/TV request. This is critical.
        if "Range" in self.headers and "Range" not in req_headers and "range" not in req_headers:
            req_headers["Range"] = self.headers.get("Range")

        # Avoid gzip/deflate if possible (we may rewrite m3u8).
        if "Accept-Encoding" not in req_headers and "accept-encoding" not in req_headers:
            req_headers["Accept-Encoding"] = "identity"

        # Ensure a UA (some hosts 403 without it)
        if "User-Agent" not in req_headers and "user-agent" not in req_headers:
            req_headers["User-Agent"] = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
            )

        method = "GET" if send_body else "HEAD"

        try:
            try:
                target_host = urllib.parse.urlsplit(target_url).hostname or "unknown"
            except Exception:
                target_host = "unknown"
            LOG.debug("Proxying %s media from host=%s", method, target_host)
            req = urllib.request.Request(target_url, headers=req_headers, method=method)

            with urllib.request.urlopen(req, timeout=15) as response:
                status = getattr(response, "status", 200)
                self.send_response(status)

                # Determine whether to rewrite m3u8 playlists
                path = urllib.parse.urlparse(response.geturl()).path
                is_m3u8 = path.endswith(".m3u8")

                # Copy headers, excluding hop-by-hop. Only skip Content-Length when rewriting.
                sent_content_type = False
                content_type_override = "application/vnd.apple.mpegurl" if is_m3u8 else None

                for k, v in response.getheaders():
                    lk = k.lower()
                    if lk in _HOP_BY_HOP_HEADERS:
                        continue
                    if is_m3u8 and lk == "content-length":
                        continue
                    if lk == "content-type":
                        sent_content_type = True
                        if is_m3u8:
                            # override later
                            continue
                    self.send_header(k, v)

                if content_type_override and not sent_content_type:
                    self.send_header("Content-Type", content_type_override)
                elif content_type_override and sent_content_type:
                    # Replace Content-Type for m3u8
                    self.send_header("Content-Type", content_type_override)

                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")

                if not send_body:
                    self.end_headers()
                    return

                if is_m3u8:
                    content = response.read()
                    try:
                        text = content.decode("utf-8", errors="ignore")
                        new_lines = []
                        base_url = response.geturl()
                        headers_val = query.get("headers", [None])[0]
                        headers_param = ""
                        if headers_val:
                            headers_param = "&headers=" + urllib.parse.quote(headers_val, safe="")
                        token_path = urllib.parse.quote(
                            str(getattr(self.server, "proxy_token", "") or ""), safe=""
                        )

                        for line in text.splitlines():
                            s = line.strip()
                            if not s or s.startswith("#"):
                                new_lines.append(line)
                                continue

                            # Relative segment/playlist -> absolute
                            abs_url = urllib.parse.urljoin(base_url, s)
                            # Point back through proxy so segments carry headers/range too
                            new_lines.append(
                                f"/{token_path}/proxy?url={urllib.parse.quote(abs_url, safe='')}"
                                f"{headers_param}"
                            )

                        out_text = "\n".join(new_lines) + "\n"
                        out = out_text.encode("utf-8")
                        self.send_header("Content-Length", str(len(out)))
                        self.end_headers()
                        self.wfile.write(out)
                    except Exception as e:
                        LOG.error("Failed to rewrite m3u8: %s", e)
                        self.end_headers()
                        self.wfile.write(content)
                else:
                    self.end_headers()
                    try:
                        while True:
                            chunk = response.read(64 * 1024)
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                        return
                    except Exception as e:
                        LOG.error("Error writing to client: %s", e)
        except urllib.error.HTTPError as e:
            # urllib uses exceptions for HTTP status codes
            try:
                self.send_response(e.code)
                for k, v in getattr(e, "headers", {}).items():
                    if k and k.lower() not in _HOP_BY_HOP_HEADERS:
                        self.send_header(k, v)
                self.send_header("Connection", "close")
                self.end_headers()
            except Exception:
                pass
        except Exception as e:
            LOG.error("Proxy error: %s", e)
            try:
                self.send_error(500, str(e))
            except Exception:
                pass

    def log_message(self, format, *args):
        """Never expose capability tokens, signed media URLs, paths, or headers."""
        if LOG.isEnabledFor(logging.DEBUG):
            try:
                LOG.debug("StreamProxy client=%s status=%s", self.client_address[0], args[1])
            except Exception:
                pass


class StreamProxy:
    def __init__(self):
        self.server: Optional[_QuietThreadingTCPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = 0
        self.converters: Dict[str, HLSConverter] = {}
        self.lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False
        self._token = secrets.token_urlsafe(32)

    def start(self):
        if self.server:
            return

        # Bind to all interfaces so Chromecast/TV can connect.
        self.server = _QuietThreadingTCPServer(("0.0.0.0", 0), StreamProxyHandler)
        self.server.proxy_token = self._token
        self.port = self.server.server_address[1]
        self._running = True

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

        self._cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._cleanup_thread.start()

        LOG.info("StreamProxy listening on 0.0.0.0:%s", self.port)

    def stop(self):
        self._running = False
        if self.server:
            try:
                self.server.shutdown()
            except Exception:
                pass
            try:
                self.server.server_close()
            except Exception:
                pass
            self.server = None
            self.thread = None

        with self.lock:
            for c in list(self.converters.values()):
                try:
                    c.stop()
                except Exception:
                    pass
            self.converters.clear()

    def _get_url_host(self, device_ip: Optional[str]) -> str:
        """
        Pick the best host to embed in URLs.
        - For local playback (no device_ip): use 127.0.0.1.
        - For Chromecast/TV: compute the local interface IP used to reach device_ip.
        """
        if not device_ip:
            return "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((device_ip, 1))
            ip = s.getsockname()[0]
            s.close()
            if not ip:
                return "127.0.0.1"
            return ip
        except Exception:
            return "127.0.0.1"

    def get_proxied_url(self, target_url: str, headers: Optional[Dict[str, str]] = None, device_ip: Optional[str] = None):
        if not self.server:
            self.start()

        params = {"url": target_url}
        if headers:
            clean_headers = {k: str(v) for k, v in headers.items() if v is not None and k != "_extra"}
            json_str = json.dumps(clean_headers)
            b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")
            params["headers"] = b64_str

        query = urllib.parse.urlencode(params)
        host = self._get_url_host(device_ip)
        token = urllib.parse.quote(self._token, safe="")
        return f"http://{host}:{self.port}/{token}/proxy?{query}"

    def get_transcoded_url(self, target_url: str, headers: Optional[Dict[str, str]] = None, device_ip: Optional[str] = None):
        if not self.server:
            self.start()

        session_id = hashlib.md5(target_url.encode("utf-8")).hexdigest()

        with self.lock:
            if session_id not in self.converters:
                self.converters[session_id] = HLSConverter(target_url, headers)
            else:
                self.converters[session_id].touch()

        host = self._get_url_host(device_ip)
        token = urllib.parse.quote(self._token, safe="")
        return f"http://{host}:{self.port}/{token}/transcode/{session_id}/stream.m3u8"

    def get_file_url(self, file_path: str, device_ip: Optional[str] = None) -> str:
        if not self.server:
            self.start()

        host = self._get_url_host(device_ip)
        b64_path = _safe_b64encode(file_path.encode("utf-8"))
        query = urllib.parse.urlencode({"path": b64_path})
        token = urllib.parse.quote(self._token, safe="")
        return f"http://{host}:{self.port}/{token}/file?{query}"

    def get_converter(self, session_id):
        with self.lock:
            return self.converters.get(session_id)

    def _cleanup_loop(self):
        while self._running:
            time.sleep(10)
            now = time.time()
            dead = []
            with self.lock:
                for sid, conv in self.converters.items():
                    if now - conv.last_access > 60:
                        try:
                            conv.stop()
                        except Exception:
                            pass
                        dead.append(sid)
                for sid in dead:
                    try:
                        del self.converters[sid]
                    except Exception:
                        pass


import atexit

# Global instance
_PROXY = StreamProxy()
atexit.register(_PROXY.stop)


def get_proxy():
    return _PROXY
