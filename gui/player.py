import wx
import vlc
import threading
import time
import sqlite3
import platform
import logging
import webbrowser
import json
import subprocess
import sys
from core import utils
from core import discovery
from core import playback_state
from core.casting import CastingManager
from urllib.parse import urlparse
from core.range_cache_proxy import get_range_cache_proxy
from core.stream_proxy import get_proxy as get_stream_proxy
from core.audio_silence import merge_ranges, merge_ranges_with_gap, scan_audio_for_silence
from core.dependency_check import _log
from .hotkeys import HoldRepeatHotkeys

log = logging.getLogger(__name__)

MIN_FORCE_SAVE_MS = 2000
MIN_TRIVIAL_POSITION_MS = 1000

_SEEKABLE_EXTENSIONS = (
    ".mp3",
    ".m4a",
    ".m4b",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".flac",
    ".mp4",
    ".m4v",
    ".webm",
    ".mkv",
    ".mov",
)

# Prefer AAC/M4A for broader compatibility with older/bundled VLC builds.
# Fall back to the previous bestaudio behavior when M4A is unavailable.
_YTDLP_VLC_AUDIO_FORMAT = "bestaudio[ext=m4a]/bestaudio[ext=mp4]/bestaudio/best"


def _is_googlevideo_url(url: str | None) -> bool:
    try:
        raw = str(url or "").strip()
        if not raw:
            return False
        host = str(urlparse(raw).hostname or "").strip().lower()
        return bool(host) and host.endswith("googlevideo.com")
    except Exception:
        return False


def _should_force_local_stream_proxy(url: str | None, *, is_frozen: bool) -> bool:
    try:
        return bool(is_frozen) and _is_googlevideo_url(url)
    except Exception:
        return False


def _is_ytdlp_cookie_load_error(exc_or_msg) -> bool:
    text = str(exc_or_msg or "").lower()
    if not text:
        return False
    return "failed to load cookies" in text or "cookieloaderror" in text


def _is_ytdlp_dpapi_cookie_error(exc_or_msg) -> bool:
    text = str(exc_or_msg or "").lower()
    if not text:
        return False
    return "dpapi" in text or "failed to decrypt with dpapi" in text


def _extract_ytdlp_info_via_cli(
    url: str,
    *,
    headers: dict | None = None,
    cookie_source: tuple | None = None,
    timeout_s: int = 30,
) -> dict:
    target_url = str(url or "").strip()
    if not target_url:
        raise RuntimeError("yt-dlp CLI: empty URL")

    hdrs = dict(headers or {})
    user_agent = str(
        hdrs.get("User-Agent")
        or hdrs.get("user-agent")
        or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ).strip()
    referer = target_url

    cmd = [
        "yt-dlp",
        "--dump-single-json",
        "--no-playlist",
        "--format",
        _YTDLP_VLC_AUDIO_FORMAT,
        "--extractor-args",
        "youtube:player_client=android_vr,android",
        "--quiet",
        "--no-warnings",
        "--no-progress",
        "--geo-bypass",
        "--color",
        "never",
        "--user-agent",
        user_agent,
        "--referer",
        referer,
    ]

    for key, value in hdrs.items():
        key_s = str(key or "").strip()
        if not key_s or key_s.lower() in ("user-agent", "referer"):
            continue
        val_s = str(value or "").strip()
        if not val_s:
            continue
        cmd.extend(["--add-header", f"{key_s}: {val_s}"])

    if isinstance(cookie_source, tuple) and cookie_source:
        browser = str(cookie_source[0] or "").strip()
        if browser:
            cmd.extend(["--cookies-from-browser", browser])

    cmd.append(target_url)

    try:
        timeout_s = max(8, min(120, int(timeout_s or 30)))
    except Exception:
        timeout_s = 30

    try:
        from core.dependency_check import _get_startup_info

        creationflags = 0
        startupinfo = None
        if platform.system().lower() == "windows":
            creationflags = 0x08000000
            startupinfo = _get_startup_info()

        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            creationflags=creationflags,
            startupinfo=startupinfo,
            timeout=timeout_s,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise RuntimeError("yt-dlp CLI not found on PATH") from e

    rc = getattr(res, "returncode", -1)
    try:
        rc = int(rc)
    except Exception:
        rc = -1
    out = str(getattr(res, "stdout", "") or "").strip()
    err = str(getattr(res, "stderr", "") or "").strip()
    if rc != 0:
        msg = err or out or f"yt-dlp CLI failed (exit {rc})"
        raise RuntimeError(msg)
    if not out:
        raise RuntimeError("yt-dlp CLI returned no JSON output")

    try:
        info = json.loads(out)
    except Exception as e:
        raise RuntimeError(f"yt-dlp CLI returned invalid JSON: {e}") from e

    if not isinstance(info, dict):
        raise RuntimeError("yt-dlp CLI returned unexpected JSON payload")

    if "entries" in info:
        try:
            entries = list(info.get("entries") or [])
            if entries:
                first = entries[0]
                if isinstance(first, dict):
                    info = first
        except Exception:
            pass

    return info


def _should_reapply_seek(target_ms: int, current_ms: int, tolerance_ms: int, remaining_retries: int) -> bool:
    try:
        if remaining_retries <= 0:
            return False
        if current_ms < 0:
            return True
        return abs(int(current_ms) - int(target_ms)) > int(tolerance_ms)
    except Exception:
        return False


class CastDialog(wx.Dialog):
    def __init__(self, parent, manager: CastingManager):
        super().__init__(parent, title="Cast to Device", size=(400, 300))
        self.manager = manager
        self.devices = []
        self.selected_device = None
        
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        self.list_box = wx.ListBox(self, style=wx.LB_SINGLE)
        sizer.Add(self.list_box, 1, wx.EXPAND | wx.ALL, 5)
        
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        refresh_btn = wx.Button(self, label="Refresh")
        refresh_btn.Bind(wx.EVT_BUTTON, self.on_refresh)
        btn_sizer.Add(refresh_btn, 0, wx.ALL, 5)
        
        connect_btn = wx.Button(self, label="Connect")
        connect_btn.Bind(wx.EVT_BUTTON, self.on_connect)
        btn_sizer.Add(connect_btn, 0, wx.ALL, 5)
        
        cancel_btn = wx.Button(self, label="Cancel")
        cancel_btn.Bind(wx.EVT_BUTTON, self.on_cancel)
        btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER | wx.ALL, 5)
        
        self.SetSizer(sizer)
        self.Centre()
        
        # Initial scan
        self.on_refresh(None)

    def on_refresh(self, event):
        self.list_box.Clear()
        self.list_box.Append("Scanning...")
        threading.Thread(target=self._scan, daemon=True).start()

    def _scan(self):
        self.devices = self.manager.discover_all()
        wx.CallAfter(self._update_list)

    def _update_list(self):
        self.list_box.Clear()
        if not self.devices:
            self.list_box.Append("No devices found")
            return
            
        for dev in self.devices:
            self.list_box.Append(dev.display_name)

    def on_connect(self, event):
        sel = self.list_box.GetSelection()
        if sel != wx.NOT_FOUND and sel < len(self.devices):
            self.selected_device = self.devices[sel]
            
            # Disable UI while connecting
            self.list_box.Disable()
            self.FindWindowByLabel("Connect").Disable()
            self.FindWindowByLabel("Refresh").Disable()
            self.FindWindowByLabel("Cancel").Disable()
            
            # Show busy cursor
            wx.BeginBusyCursor()
            
            threading.Thread(target=self._connect_thread, args=(self.selected_device,), daemon=True).start()

    def _connect_thread(self, device):
        success = False
        try:
            # This blocks the thread, not the GUI
            self.manager.connect(device)
            success = True
        except Exception as e:
            wx.CallAfter(self._on_connect_error, str(e))
        finally:
            wx.CallAfter(self._on_connect_complete, success)

    def _on_connect_error(self, error_msg):
        wx.MessageBox(f"Connection failed: {error_msg}", "Error", wx.ICON_ERROR)

    def _on_connect_complete(self, success):
        wx.EndBusyCursor()
        if success:
            self.EndModal(wx.ID_OK)
        else:
            # Re-enable UI
            self.list_box.Enable()
            self.FindWindowByLabel("Connect").Enable()
            self.FindWindowByLabel("Refresh").Enable()
            self.FindWindowByLabel("Cancel").Enable()

    def on_cancel(self, event):
        self.EndModal(wx.ID_CANCEL)


class PlayerFrame(wx.Frame):
    def __init__(self, parent, config_manager):
        super().__init__(parent, title="Audio Player", size=(520, 260), style=wx.DEFAULT_FRAME_STYLE | wx.STAY_ON_TOP)
        self.config_manager = config_manager
        
        # Casting
        self.casting_manager = CastingManager()
        self.casting_manager.start()
        self.is_casting = False
        self._cast_last_pos_ms = 0
        self._cast_local_was_playing = False
        self._cast_poll_ts = 0.0

        # Cast handoff tracking
        self._cast_handoff_source_url = None
        self._cast_handoff_target_ms = 0
        self._cast_handoff_attempts_left = 0
        self._timer_interval_ms = 0

        # Resume Seek State
        self._pending_resume_seek_ms = None
        self._pending_resume_seek_attempts = 0
        self._pending_resume_seek_max_attempts = 25
        self._pending_resume_paused = False

        # Slider State
        self._is_dragging_slider = False

        # VLC Instance
        cache_ms = int(self.config_manager.get("vlc_network_caching_ms", 500))
        if cache_ms < 0: cache_ms = 0
        file_cache_ms = max(500, cache_ms)
        self.instance = None
        self.player = None
        self.event_manager = None
        self.initialized = False
        self._init_vlc()
        
        self.timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.on_timer, self.timer)
        
        self.is_playing = False
        self.duration = 0
        self.current_chapters = []
        self.chapter_marks = []
        self._chapter_pending_idx = None
        self._chapter_closeup_supported = False
        self._chapter_last_commit_idx = None
        self._chapter_last_commit_ts = 0.0
        self._chapter_menu_show_item = None
        self._chapter_menu_prev_item = None
        self._chapter_menu_next_item = None
        self.current_url = None
        self.current_article_id = None
        self._load_seq = 0
        self._active_load_seq = 0
        self.current_title = "No Track Loaded"

        # Persistent playback resume (stored locally in SQLite, keyed by the input URL).
        self._resume_id = None
        self._resume_fallback_id = None
        self._resume_memory_state = {}
        self._resume_pending_db_upserts = {}
        self._resume_pending_db_seek_supported = {}
        self._resume_pending_db_flush_calllater = None
        self._resume_seek_supported_marked = set()
        self._resume_last_save_ts = 0.0
        self._resume_restore_inflight = False
        self._resume_restore_id = None
        self._resume_restore_target_ms = None
        self._resume_restore_attempts = 0
        self._resume_restore_last_attempt_ts = 0.0
        self._resume_restore_started_ts = 0.0
        self._resume_seek_save_calllater = None
        self._resume_seek_save_id = None
        self._stopped_needs_resume = False
        self._shutdown_done = False

        # Seek coalescing / debounce
        self._seek_target_ms = None
        self._seek_target_ts = 0.0

        self._last_vlc_time_ms = 0

        # When the user taps seek keys rapidly, repeatedly calling VLC set_time()
        # causes audio stalls (buffer flush + re-buffer). We coalesce seek inputs:
        # - UI jumps immediately on each input.
        # - VLC gets at most one seek every _seek_apply_max_rate_s while holding.
        # - After the last input, we apply the final target after _seek_apply_debounce_s.
        self._seek_apply_last_ts = 0.0  # last time we actually called VLC set_time()
        self._seek_apply_target_ms = None
        self._seek_apply_calllater = None
        self._seek_input_ts = 0.0  # last seek input timestamp
        self._seek_apply_reason = None
        self._seek_apply_reason_ts = 0.0
        self._seek_log_last_ts = 0.0
        self._last_vlc_warn_ts = 0.0

        try:
            self._seek_apply_debounce_s = float(self.config_manager.get("seek_apply_debounce_s", 0.18) or 0.18)
        except Exception:
            self._seek_apply_debounce_s = 0.18
        try:
            self._seek_apply_max_rate_s = float(self.config_manager.get("seek_apply_max_rate_s", 0.35) or 0.35)
        except Exception:
            self._seek_apply_max_rate_s = 0.35

        # Clamp to sane values
        self._seek_apply_debounce_s = max(0.06, min(0.50, float(self._seek_apply_debounce_s)))
        self._seek_apply_max_rate_s = max(0.12, min(1.00, float(self._seek_apply_max_rate_s)))

# Authoritative position tracking
        self._pos_ms = 0
        self._pos_ts = time.monotonic()
        self._pos_allow_backwards_until_ts = 0.0
        self._pos_last_timer_ts = 0.0

        # Seek guard
        self._seek_guard_target_ms = None
        self._seek_guard_attempts_left = 0
        self._seek_guard_reapply_left = 0
        self._seek_guard_calllater = None
        self._seek_guard_last_cur_ms = None
        self._seek_guard_last_delta_ms = None
        self._seek_guard_last_progress_ts = 0.0

        # Range-cache proxy recovery state
        self._last_orig_url = None
        self._last_vlc_url = None
        self._last_used_range_proxy = False
        self._last_range_proxy_headers = None
        self._last_vlc_http_headers = None
        self._last_range_proxy_cache_dir = None
        self._last_range_proxy_prefetch_kb = None
        self._last_range_proxy_initial_burst_kb = None
        self._last_range_proxy_initial_inline_kb = None
        self._range_proxy_retry_count = 0
        self._range_proxy_last_stall_recover_ts = 0.0
        self._last_used_stream_proxy = False
        self._stream_proxy_retry_count = 0
        self._stream_proxy_last_stall_recover_ts = 0.0
        self._last_load_chapters = None
        self._last_load_title = None

        # External status change listeners (e.g. search dialog)
        self._status_change_callbacks = []

        # Silence skip
        self._silence_scan_thread = None
        self._silence_scan_abort = None
        self._silence_ranges = []
        self._silence_scan_ready = False
        self._silence_skip_active_target = None
        self._silence_skip_last_idx = None
        self._silence_skip_last_ts = 0.0
        self._silence_skip_last_target_ms = None
        self._silence_skip_last_seek_ts = 0.0
        self._silence_skip_floor_ms = 0
        self._silence_skip_reset_floor = False
        self._silence_skip_pause_until_ts = 0.0
        self._silence_skip_verify_until_ts = 0.0
        self._silence_skip_verify_target_ms = None
        self._silence_skip_verify_source_ms = None
        self._silence_skip_verify_attempted = False
        self._silence_skip_probe_seq = 0
        self._silence_skip_probe_calllaters = []

        # Status + async load tracking (avoid blocking UI during media resolve)
        self._status_text = ""
        self._last_status_state = None
        self._last_status_update_ts = 0.0
        self._load_start_ts = 0.0
        self._silence_scan_pending = False
        self._silence_scan_pending_info = None

        # Playback speed handling
        self.playback_speed = float(self.config_manager.get("playback_speed", 1.0))
        # Media key settings
        self.volume = int(self.config_manager.get("volume", 100))
        self.volume_step = int(self.config_manager.get("volume_step", 5))
        self.seek_back_ms = int(self.config_manager.get("seek_back_ms", 10000))
        self.seek_forward_ms = int(self.config_manager.get("seek_forward_ms", self.seek_back_ms))
        if self.seek_forward_ms != self.seek_back_ms:
            self.seek_forward_ms = int(self.seek_back_ms)
            try:
                self.config_manager.set("seek_forward_ms", int(self.seek_forward_ms))
            except Exception:
                pass
        self._volume_slider_updating = False
        self._current_use_ytdlp = False

        self.init_ui()
        self.Bind(wx.EVT_CLOSE, self.on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self.on_char_hook)

        self._media_hotkeys = HoldRepeatHotkeys(self, hold_delay_s=0.2, repeat_interval_s=0.3, poll_interval_ms=200)

        # Apply initial volume
        self.set_volume_percent(self.volume, persist=False)
        
        # Update UI with initial speed
        self.set_playback_speed(self.playback_speed)

    # ---------------------------------------------------------------------
    # Window helpers
    # ---------------------------------------------------------------------

    def _init_vlc(self) -> bool:
        cache_ms = int(self.config_manager.get("vlc_network_caching_ms", 500))
        if cache_ms < 0:
            cache_ms = 0
        file_cache_ms = max(500, cache_ms)
        try:
            self.instance = vlc.Instance(
                "--no-video",
                "--input-fast-seek",
                "--aout=directsound",
                f"--network-caching={cache_ms}",
                f"--file-caching={file_cache_ms}",
                "--http-reconnect",
            )
            self.player = self.instance.media_player_new()
            self.event_manager = self.player.event_manager()
            try:
                self.event_manager.event_attach(vlc.EventType.MediaPlayerEncounteredError, self._on_vlc_error)
            except Exception:
                pass
            try:
                self.apply_preferred_soundcard()
            except Exception:
                pass
            self.initialized = True
            return True
        except Exception as e:
            try:
                self.instance = None
                self.player = None
                self.event_manager = None
            except Exception:
                pass
            self.initialized = False
            wx.CallAfter(
                wx.MessageBox,
                f"VLC could not be initialized: {e}\n\n"
                "Please ensure VLC media player is installed (64-bit version recommended).",
                "VLC Error",
                wx.OK | wx.ICON_ERROR,
            )
            return False

    def _ensure_vlc_ready(self) -> bool:
        try:
            if self.initialized and self.player is not None and self.instance is not None:
                return True
        except Exception:
            pass
        return self._init_vlc()

    def _get_preferred_soundcard_id(self) -> str:
        try:
            raw = self.config_manager.get("preferred_soundcard", "")
        except Exception:
            raw = ""
        value = str(raw or "").strip()
        if value.lower() in {"default", "system", "system_default"}:
            return ""
        return value

    def apply_preferred_soundcard(self) -> bool:
        player = getattr(self, "player", None)
        if player is None:
            return False
        device_id = self._get_preferred_soundcard_id()
        prev_device_id = getattr(self, "_last_applied_soundcard_id", None)
        try:
            if device_id:
                try:
                    # mmdevice supports selecting specific Windows endpoint IDs.
                    player.audio_output_set("mmdevice")
                except Exception:
                    pass
                player.audio_output_device_set(None, str(device_id))
            else:
                player.audio_output_device_set(None, None)
            self._last_applied_soundcard_id = str(device_id or "")
            if str(prev_device_id or "") != str(device_id or ""):
                if device_id:
                    log.info("Applied preferred soundcard: %s", device_id)
                else:
                    log.info("Using system default soundcard")
            return True
        except Exception:
            log.exception("Failed to apply preferred soundcard")
            return False

    def _set_status(self, text: str) -> None:
        """Update the status label without spamming screen readers."""
        try:
            new_text = str(text or "")
        except Exception:
            new_text = ""

        try:
            if new_text == str(getattr(self, "_status_text", "") or ""):
                return
        except Exception:
            pass

        def _apply() -> None:
            try:
                if getattr(self, "status_lbl", None):
                    self.status_lbl.SetLabel(new_text)
            except Exception:
                pass
            try:
                self._status_text = new_text
                self._last_status_update_ts = float(time.monotonic())
            except Exception:
                pass
            try:
                for cb in list(getattr(self, "_status_change_callbacks", ())):
                    try:
                        cb(new_text)
                    except Exception:
                        pass
            except Exception:
                pass

        try:
            if wx.IsMainThread():
                _apply()
            else:
                wx.CallAfter(_apply)
        except Exception:
            pass

    def _current_position_ms(self) -> int:
        """
        Best-effort current position in ms, favoring recent seek targets and
        UI-tracked position with elapsed time when playing.
        """
        now = time.monotonic()
        try:
            tgt = getattr(self, "_seek_target_ms", None)
            tgt_ts = float(getattr(self, "_seek_target_ts", 0.0) or 0.0)
        except Exception:
            tgt = None
            tgt_ts = 0.0

        base = 0
        if tgt is not None and (now - tgt_ts) < 2.5:
            try:
                base = int(tgt)
            except Exception:
                base = 0
        else:
            try:
                base = int(getattr(self, "_pos_ms", 0) or 0)
            except Exception:
                base = 0

        try:
            if bool(getattr(self, "is_playing", False)):
                pos_ts = float(getattr(self, "_pos_ts", 0.0) or 0.0)
                if pos_ts > 0:
                    base += int(max(0.0, now - pos_ts) * 1000.0)
        except Exception:
            pass

        if base < 0:
            base = 0
        try:
            dur = int(getattr(self, "duration", 0) or 0)
            if dur > 0 and base > dur:
                base = dur
        except Exception:
            pass
        return int(base)

    # ---------------------------------------------------------------------
    # Persistent resume (SQLite overlay)
    # ---------------------------------------------------------------------

    def _get_config_int(self, key: str, default: int) -> int:
        try:
            return int(self.config_manager.get(key, default))
        except (TypeError, ValueError):
            return default

    def _get_config_bool(self, key: str, default: bool) -> bool:
        val = self.config_manager.get(key, default)
        if isinstance(val, str):
            norm = val.strip().lower()
            if norm in ("true", "1", "yes", "on"):
                return True
            if norm in ("false", "0", "no", "off"):
                return False
            return bool(default)
        return bool(val)

    def _resume_feature_enabled(self) -> bool:
        return self._get_config_bool("resume_playback", True)

    def _get_resume_id(self) -> str | None:
        rid = getattr(self, "_resume_id", None)
        if rid:
            return str(rid)
        url = getattr(self, "current_url", None)
        if url:
            return str(url)
        return None

    def _set_resume_ids(self, url: str, article_id: object | None) -> None:
        fallback = str(url) if url else None

        primary = None
        if article_id is not None:
            try:
                aid = str(article_id).strip()
            except TypeError as e:
                log.warning("Could not convert article_id to string: %s", e)
                aid = ""
            if aid:
                primary = f"article:{aid}"

        self._resume_id = primary or fallback
        self._resume_fallback_id = fallback if primary else None

    def _current_input_looks_seekable(self) -> bool:
        url = ""
        try:
            url = str(getattr(self, "current_url", "") or "")
        except Exception as e:
            log.debug("Could not get current_url for seekable check: %s", e)
            url = ""
        if not url:
            return False
        low = url.lower()
        if ".m3u8" in low:
            return False
        try:
            path = urlparse(low).path.lower() or low
        except Exception as e:
            log.debug("Could not parse URL path for seekable check: %s", e)
            path = low
        return path.endswith(_SEEKABLE_EXTENSIONS)

    def _cache_resume_state(
        self,
        resume_id: str,
        position_ms: int,
        duration_ms: int | None,
        title: str | None,
        completed: bool,
        seek_supported: bool | None = None,
    ) -> None:
        if not resume_id:
            return
        try:
            self._resume_memory_state[str(resume_id)] = playback_state.PlaybackState(
                id=str(resume_id),
                position_ms=int(position_ms or 0),
                duration_ms=(int(duration_ms) if duration_ms is not None else None),
                updated_at=int(time.time()),
                completed=bool(completed),
                seek_supported=seek_supported,
                title=(str(title) if title else None),
            )
        except Exception:
            log.exception("Failed to cache resume state for %s", resume_id)

    def _save_playback_state(
        self,
        resume_id: str,
        position_ms: int,
        duration_ms: int | None,
        title: str | None,
        completed: bool,
        *,
        seek_supported: bool | None = None,
    ) -> bool:
        """Caches state and persists it, queuing a retry if SQLite is locked.

        Returns True if the state was written to DB or queued for a later flush.
        """
        if not resume_id:
            return False

        rid = str(resume_id)
        pos_ms = int(position_ms or 0)

        self._cache_resume_state(
            rid,
            pos_ms,
            duration_ms,
            title,
            bool(completed),
            seek_supported=seek_supported,
        )

        ok = False
        try:
            ok = playback_state.upsert_playback_state(
                rid,
                pos_ms,
                duration_ms=duration_ms,
                title=title,
                completed=bool(completed),
                seek_supported=seek_supported,
            )
        except Exception:
            log.exception("Failed to persist playback_state for %s", rid)
            ok = False

        if ok:
            return True

        try:
            self._queue_resume_db_upsert(
                rid,
                pos_ms,
                duration_ms,
                title,
                bool(completed),
                seek_supported=seek_supported,
            )
            return True
        except Exception:
            log.exception("Failed to queue playback_state upsert for %s", rid)
            return False

    def _get_playback_state_cached(self, resume_id: str) -> playback_state.PlaybackState | None:
        """Return playback state for resume_id using in-memory cache, falling back to SQLite."""
        if not resume_id:
            return None

        rid = str(resume_id)

        state = self._resume_memory_state.get(rid)
        if state is not None:
            return state

        try:
            state = playback_state.get_playback_state(rid)
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                log.debug("playback_state is locked while reading %s; skipping", rid)
                return None
            log.exception("Failed to read playback_state for resume: %s", rid)
            return None
        except sqlite3.Error:
            log.exception("Failed to read playback_state for resume: %s", rid)
            return None
        except Exception:
            log.exception("Unexpected error while reading playback_state for resume: %s", rid)
            return None

        if state is None:
            return None

        self._resume_memory_state[rid] = state
        return state

    def _schedule_resume_db_flush(self, delay_ms: int = 450) -> None:
        try:
            if self._resume_pending_db_flush_calllater is not None:
                return
            self._resume_pending_db_flush_calllater = wx.CallLater(int(max(50, delay_ms)), self._flush_pending_resume_db_writes)
        except Exception:
            self._resume_pending_db_flush_calllater = None

    def _queue_resume_db_upsert(
        self,
        resume_id: str,
        position_ms: int,
        duration_ms: int | None,
        title: str | None,
        completed: bool,
        seek_supported: bool | None = None,
    ) -> None:
        if not resume_id:
            return
        try:
            self._resume_pending_db_upserts[str(resume_id)] = {
                "position_ms": int(position_ms or 0),
                "duration_ms": (int(duration_ms) if duration_ms is not None else None),
                "title": (str(title) if title else None),
                "completed": bool(completed),
                "seek_supported": seek_supported,
            }
        except Exception:
            log.exception("Failed to queue resume DB upsert for %s", resume_id)
            return
        self._schedule_resume_db_flush()

    def _queue_resume_db_seek_supported(self, resume_id: str, seek_supported: bool) -> None:
        if not resume_id:
            return
        try:
            self._resume_pending_db_seek_supported[str(resume_id)] = bool(seek_supported)
        except Exception:
            log.exception("Failed to queue resume DB seek_supported for %s", resume_id)
            return
        self._schedule_resume_db_flush()

    def _flush_pending_items(
        self,
        pending: dict,
        write_item,
        retry_value,
        drop_log_message: str,
    ) -> dict:
        remaining = {}
        for rid, payload in pending.items():
            try:
                ok = write_item(str(rid), payload)
                if ok is False:
                    remaining[str(rid)] = retry_value(payload)
            except Exception:
                log.exception(drop_log_message, rid)
        return remaining

    def _flush_pending_resume_upserts(self) -> dict:
        pending = self._resume_pending_db_upserts.copy()
        remaining = self._flush_pending_items(
            pending,
            lambda rid, payload: playback_state.upsert_playback_state(
                str(rid),
                int(payload.get("position_ms", 0) or 0),
                duration_ms=payload.get("duration_ms", None),
                title=payload.get("title", None),
                completed=bool(payload.get("completed", False)),
                seek_supported=payload.get("seek_supported", None),
            ),
            lambda payload: dict(payload),
            "Failed to flush queued playback_state upsert for %s; dropping item",
        )
        self._resume_pending_db_upserts = remaining
        return remaining

    def _flush_pending_seek_supported_updates(self) -> dict:
        pending_seek = self._resume_pending_db_seek_supported.copy()
        if not pending_seek:
            return {}
        remaining_seek = self._flush_pending_items(
            pending_seek,
            lambda rid, val: playback_state.set_seek_supported(str(rid), bool(val)),
            lambda val: bool(val),
            "Failed to flush queued seek_supported update for %s; dropping item",
        )
        self._resume_pending_db_seek_supported = remaining_seek
        return remaining_seek

    def _flush_pending_resume_db_writes(self) -> None:
        self._resume_pending_db_flush_calllater = None

        remaining = self._flush_pending_resume_upserts()
        remaining_seek = self._flush_pending_seek_supported_updates()

        if remaining or remaining_seek:
            self._schedule_resume_db_flush(delay_ms=900)

    def _stop_calllater(self, attr_name: str, log_message: str) -> None:
        try:
            calllater = getattr(self, attr_name, None)
            if calllater is not None:
                calllater.Stop()
        except Exception:
            log.exception(log_message)
        finally:
            try:
                setattr(self, attr_name, None)
            except Exception:
                pass

    def _cancel_scheduled_resume_save(self) -> None:
        try:
            self._stop_calllater("_resume_seek_save_calllater", "Failed to cancel scheduled resume save")
        finally:
            self._resume_seek_save_id = None

    def _reset_auto_resume_state(self) -> None:
        """Resets all state related to an in-progress auto-resume seek."""
        self._pending_resume_seek_ms = None
        self._pending_resume_seek_attempts = 0
        self._pending_resume_paused = False
        self._resume_restore_inflight = False
        self._resume_restore_id = None
        self._resume_restore_target_ms = None
        self._resume_restore_attempts = 0
        self._resume_restore_last_attempt_ts = 0.0
        self._resume_restore_started_ts = 0.0

    def _note_user_seek(self) -> None:
        try:
            self._stopped_needs_resume = False
            # User-initiated seeks should override any pending auto-resume seek.
            if getattr(self, "_resume_restore_inflight", False) and getattr(self, "_pending_resume_seek_ms", None) is not None:
                self._reset_auto_resume_state()
            self._silence_skip_reset_floor = True
            pause_s = 1.2
            try:
                url = getattr(self, "current_url", "") or ""
                if url.startswith("http") and not ("127.0.0.1" in url or "localhost" in url):
                    pause_s = 2.5
            except Exception:
                pause_s = 1.2
            self._silence_skip_pause_until_ts = float(time.monotonic()) + float(pause_s)
            self._silence_skip_verify_until_ts = 0.0
            self._silence_skip_verify_target_ms = None
            self._silence_skip_verify_source_ms = None
            self._silence_skip_verify_attempted = False
            try:
                self._cancel_silence_skip_probes()
            except Exception:
                pass
        except Exception:
            log.exception("Error resetting resume state on user seek")
        try:
            self._mark_current_resume_seek_supported()
        except Exception as e:
            log.debug("Error marking current resume as seek supported: %s", e)

    def _mark_current_resume_seek_supported(self) -> None:
        rid = self._get_resume_id()
        if not rid:
            return
        rid = str(rid)

        fallback = self._resume_fallback_id

        ids = [rid]
        if fallback and str(fallback) != rid:
            ids.append(str(fallback))

        for pid in ids:
            if not pid:
                continue
            if pid in self._resume_seek_supported_marked:
                continue
            self._resume_seek_supported_marked.add(pid)

            st = self._resume_memory_state.get(pid)
            if st is not None and st.seek_supported is not True:
                self._cache_resume_state(
                    pid,
                    int(st.position_ms or 0),
                    st.duration_ms,
                    st.title,
                    bool(st.completed),
                    seek_supported=True,
                )

            try:
                ok = playback_state.set_seek_supported(pid, True)
            except Exception as e:
                log.debug("Failed to persist seek_supported=True for %s: %s", pid, e)
                ok = False
            if ok is False:
                try:
                    self._queue_resume_db_seek_supported(pid, True)
                except Exception:
                    log.exception("Failed to queue seek_supported update for %s", pid)

    def _schedule_resume_save_after_seek(self, delay_ms: int = 900) -> None:
        if not self._resume_feature_enabled():
            return
        resume_id = self._get_resume_id()
        if not resume_id:
            return

        try:
            delay = max(0, int(delay_ms))
        except (TypeError, ValueError):
            delay = 900

        self._cancel_scheduled_resume_save()
        self._resume_seek_save_id = str(resume_id)

        def _tick() -> None:
            try:
                if (self._get_resume_id() or "") != str(self._resume_seek_save_id or ""):
                    return
                if getattr(self, "_resume_restore_inflight", False) and getattr(self, "_pending_resume_seek_ms", None) is not None:
                    return
                if self.is_casting:
                    pos_ms = int(getattr(self, "_cast_last_pos_ms", 0) or 0)
                else:
                    pos_ms = int(self._current_position_ms())
            except Exception:
                log.exception("Failed to get position in scheduled resume save tick")
                return

            if pos_ms < MIN_TRIVIAL_POSITION_MS:
                return

            try:
                self._persist_playback_position(force=True)
            except Exception:
                log.exception("Failed to persist playback position after seek")

        try:
            self._resume_seek_save_calllater = wx.CallLater(int(delay), _tick)
        except Exception:
            log.exception("Failed to schedule resume save")
            self._resume_seek_save_calllater = None

    def _maybe_restore_playback_position(self, resume_id: str, title: str | None) -> None:
        if not resume_id:
            return
        if not self._resume_feature_enabled():
            return

        rid = str(resume_id)

        state = self._get_playback_state_cached(rid)
        if not state or state.completed:
            return
        if state.seek_supported is False and not self._current_input_looks_seekable():
            # We previously learned this stream is not seekable, so avoid an auto-resume loop.
            return

        pos_ms = state.position_ms

        min_ms = self._get_config_int("resume_min_ms", 0)
        if pos_ms < max(0, min_ms):
            return

        complete_threshold_ms = self._get_config_int("resume_complete_threshold_ms", 60000)

        dur_ms = state.duration_ms or 0
        if dur_ms > 0 and (dur_ms - pos_ms) <= max(0, complete_threshold_ms):
            # Treat items close to the end as completed (avoid resuming to the credits).
            try:
                self._save_playback_state(
                    rid,
                    0,
                    int(dur_ms),
                    title,
                    True,
                    seek_supported=state.seek_supported,
                )
            except Exception:
                log.exception("Failed to mark playback_state as completed")
            return

        back_ms = self._get_config_int("resume_back_ms", 10000)
        back_ms = max(0, back_ms)
        # If the saved position is very early in the file, don't rewind back past 0
        # (otherwise it looks like resume did not work at all).
        if pos_ms <= back_ms:
            target_ms = pos_ms
        else:
            target_ms = pos_ms - back_ms

        self._pending_resume_seek_ms = target_ms
        self._pending_resume_seek_attempts = 0
        self._pending_resume_paused = False
        self._resume_restore_inflight = True
        self._resume_restore_id = rid
        self._resume_restore_target_ms = target_ms
        self._resume_restore_attempts = 0
        self._resume_restore_last_attempt_ts = 0.0
        self._resume_restore_started_ts = time.monotonic()
        # Avoid writing a 0-position back to the DB while the resume seek is still pending.
        self._resume_last_save_ts = time.monotonic()

    def _persist_playback_position(self, force: bool = False) -> None:
        if not self._resume_feature_enabled():
            return
        resume_id = self._get_resume_id()
        if not resume_id:
            return
        resume_id = str(resume_id)

        restore_pending = bool(getattr(self, "_resume_restore_inflight", False)) and getattr(self, "_pending_resume_seek_ms", None) is not None

        # Don't overwrite saved progress while the initial resume seek is pending.
        if restore_pending and not force:
            return

        # Even for force saves, avoid overwriting stored progress with a near-zero position while restore is pending.
        if restore_pending and force:
            try:
                if self.is_casting:
                    cur_pos_ms = int(getattr(self, "_cast_last_pos_ms", 0) or 0)
                else:
                    cur_pos_ms = int(self._current_position_ms())
            except Exception:
                cur_pos_ms = 0
            if cur_pos_ms < MIN_FORCE_SAVE_MS:
                return

        try:
            interval_s = float(self.config_manager.get("resume_save_interval_s", 15) or 15)
        except Exception:
            interval_s = 15.0
        interval_s = max(2.0, float(interval_s))

        now = float(time.monotonic())
        if not force:
            try:
                last = float(getattr(self, "_resume_last_save_ts", 0.0) or 0.0)
            except Exception:
                last = 0.0
            if (now - last) < interval_s:
                return

        try:
            if self.is_casting:
                pos_ms = int(getattr(self, "_cast_last_pos_ms", 0) or 0)
            else:
                pos_ms = int(self._current_position_ms())
        except Exception:
            pos_ms = 0

        if not force and pos_ms < MIN_TRIVIAL_POSITION_MS:
            # Avoid creating state rows for trivial playback attempts.
            return

        try:
            dur_ms = int(getattr(self, "duration", 0) or 0)
        except Exception:
            dur_ms = 0
        if dur_ms <= 0:
            dur_ms = None

        try:
            complete_threshold_ms = int(self.config_manager.get("resume_complete_threshold_ms", 60000) or 60000)
        except Exception:
            complete_threshold_ms = 60000

        completed = False
        if dur_ms is not None and int(dur_ms) > 0:
            remaining = int(dur_ms) - int(pos_ms)
            if remaining <= max(0, int(complete_threshold_ms)):
                completed = True
                pos_ms = 0

        # Avoid overwriting meaningful progress with a near-zero forced save. This can happen if
        # VLC briefly reports 0ms (e.g., during reconnect/pause glitches) right before we persist.
        if force and not completed and int(pos_ms) < int(MIN_FORCE_SAVE_MS):
            existing = self._get_playback_state_cached(resume_id)
            if existing and not existing.completed and int(existing.position_ms or 0) >= int(MIN_FORCE_SAVE_MS):
                return

        title = getattr(self, "current_title", None)
        saved = self._save_playback_state(
            resume_id,
            int(pos_ms),
            (int(dur_ms) if dur_ms is not None else None),
            (str(title) if title else None),
            bool(completed),
        )
        if saved:
            self._resume_last_save_ts = float(now)

    def focus_play_pause(self) -> None:
        try:
            if getattr(self, "play_btn", None):
                self.play_btn.SetFocus()
        except Exception:
            pass

    def show_and_focus(self) -> None:
        try:
            if not self.IsShown():
                self.Show()
            self.Raise()
            wx.CallAfter(self.focus_play_pause)
        except Exception:
            pass

    # ---------------------------------------------------------------------
    # VLC error handling
    # ---------------------------------------------------------------------

    def _on_vlc_error(self, event) -> None:
        _log("VLC encountered an error event.")
        log.debug("VLC error event")
        try:
            wx.CallAfter(self._handle_vlc_error)
        except Exception:
            log.exception("Failed to schedule VLC error handler")

    def _handle_vlc_error(self) -> None:
        log.debug("Handling VLC error")
        if self.is_casting:
            return
        if not self._last_vlc_url:
            return

        if not self._last_used_range_proxy or not self._last_orig_url:
            return

        # Preserve the best-known position so recovery doesn't jump backwards.
        try:
            ui_pos = int(getattr(self, "_pos_ms", 0) or 0)
        except Exception:
            ui_pos = 0
        try:
            vlc_pos = int(self.player.get_time() or 0)
        except Exception:
            vlc_pos = 0
        resume_ms = max(0, int(max(ui_pos, vlc_pos)))
        if resume_ms > 0:
            try:
                self._pending_resume_seek_ms = int(resume_ms)
                self._pending_resume_seek_attempts = 0
                self._pending_resume_paused = not bool(self.player.is_playing())
                self._resume_restore_inflight = False
                self._resume_restore_id = None
                self._resume_restore_target_ms = None
            except Exception:
                pass

        # First: restart proxy and retry once.
        if self._range_proxy_retry_count == 0:
            self._range_proxy_retry_count = 1
            try:
                inline_window_kb = int(self.config_manager.get('range_cache_inline_window_kb', 1024) or 1024)
                proxy = get_range_cache_proxy(
                    cache_dir=self._last_range_proxy_cache_dir,
                    prefetch_kb=int(self._last_range_proxy_prefetch_kb or 16384),
                    background_download=bool(self.config_manager.get('range_cache_background_download', True)),
                    background_chunk_kb=int(self.config_manager.get('range_cache_background_chunk_kb', 8192) or 8192),
                    inline_window_kb=inline_window_kb,
                    initial_burst_kb=int(self._last_range_proxy_initial_burst_kb or self.config_manager.get('range_cache_initial_burst_kb', 65536) or 65536),
                    initial_inline_prefetch_kb=int(self._last_range_proxy_initial_inline_kb or self.config_manager.get('range_cache_initial_inline_prefetch_kb', 1024) or 1024),
                    debug_logs=bool(self.config_manager.get('range_cache_debug', False)),
                )
                try:
                    proxy.start()
                except Exception:
                    pass
                new_url = proxy.proxify(self._last_orig_url, headers=self._last_range_proxy_headers or {})
                self._last_vlc_url = new_url
                self._load_vlc_url(new_url, http_headers=self._last_vlc_http_headers)
                return
            except Exception:
                pass

        # Second: fall back to the original URL
        if self._range_proxy_retry_count == 1:
            self._range_proxy_retry_count = 2
            try:
                self._last_used_range_proxy = False
                self._last_vlc_url = self._last_orig_url
                self._load_vlc_url(self._last_orig_url, http_headers=self._last_vlc_http_headers)
            except Exception:
                pass

    def _maybe_recover_stalled_proxy_playback(self, state, playing_now: bool, cur_ms: int) -> None:
        """Fallback when proxied playback stalls without VLC raising an error event."""
        try:
            if self.is_casting:
                return
            if not bool(getattr(self, "_last_used_range_proxy", False)):
                return
            if not str(getattr(self, "_last_orig_url", "") or "").strip():
                return
            if bool(playing_now) or int(cur_ms) > 0:
                return
            if int(getattr(self, "_range_proxy_retry_count", 0) or 0) >= 2:
                return
            load_started = float(getattr(self, "_load_start_ts", 0.0) or 0.0)
            if load_started <= 0.0:
                return
            now_mono = float(time.monotonic())
            if (now_mono - load_started) < 8.0:
                return
            try:
                import vlc as _vlc_mod
                stalled_states = (
                    _vlc_mod.State.NothingSpecial,
                    _vlc_mod.State.Opening,
                    _vlc_mod.State.Buffering,
                    _vlc_mod.State.Stopped,
                    _vlc_mod.State.Error,
                )
            except Exception:
                stalled_states = ()
            if stalled_states and state not in stalled_states:
                return
            last_recover = float(getattr(self, "_range_proxy_last_stall_recover_ts", 0.0) or 0.0)
            if (now_mono - last_recover) < 6.0:
                return
            self._range_proxy_last_stall_recover_ts = now_mono
            log.warning(
                "Detected stalled proxied playback after %.1fs (state=%s, pos=%sms); attempting recovery",
                max(0.0, now_mono - load_started),
                state,
                int(cur_ms),
            )
            self._handle_vlc_error()
        except Exception:
            pass

    def _maybe_stream_proxy_url(self, url: str, headers: dict | None = None) -> str:
        try:
            target = str(url or "").strip()
            if not target:
                return target
            low = target.lower()
            if not (low.startswith("http://") or low.startswith("https://")):
                return target
            host_name = ""
            try:
                host_name = str(urlparse(target).hostname or "").strip().lower()
            except Exception:
                host_name = ""
            if host_name in ("127.0.0.1", "localhost"):
                return target

            proxy = get_stream_proxy()
            if proxy is None:
                return target
            proxied = str(proxy.get_proxied_url(target, headers=dict(headers or {}), device_ip=None) or "").strip()
            if proxied and proxied != target:
                self._last_used_stream_proxy = True
                self._last_used_range_proxy = False
                self._last_vlc_url = proxied
                return proxied
        except Exception as e:
            log.debug("Local stream proxy fallback unavailable: %s", e)
        return url

    def _maybe_recover_stalled_direct_playback(self, state, playing_now: bool, cur_ms: int) -> None:
        """Fallback for direct YouTube media URLs that stall at startup."""
        try:
            if self.is_casting:
                return
            if bool(getattr(self, "_last_used_range_proxy", False)):
                return
            if bool(getattr(self, "_last_used_stream_proxy", False)):
                return
            orig_url = str(getattr(self, "_last_orig_url", "") or "").strip()
            if not _is_googlevideo_url(orig_url):
                return
            if bool(playing_now) or int(cur_ms) > 0:
                return
            if int(getattr(self, "_stream_proxy_retry_count", 0) or 0) >= 1:
                return
            load_started = float(getattr(self, "_load_start_ts", 0.0) or 0.0)
            if load_started <= 0.0:
                return
            now_mono = float(time.monotonic())
            if (now_mono - load_started) < 6.0:
                return
            try:
                import vlc as _vlc_mod
                stalled_states = (
                    _vlc_mod.State.NothingSpecial,
                    _vlc_mod.State.Opening,
                    _vlc_mod.State.Buffering,
                    _vlc_mod.State.Stopped,
                    _vlc_mod.State.Error,
                )
            except Exception:
                stalled_states = ()
            if stalled_states and state not in stalled_states:
                return
            last_recover = float(getattr(self, "_stream_proxy_last_stall_recover_ts", 0.0) or 0.0)
            if (now_mono - last_recover) < 6.0:
                return

            proxied = self._maybe_stream_proxy_url(orig_url, headers=getattr(self, "_last_vlc_http_headers", None))
            if not proxied or proxied == orig_url:
                return

            self._stream_proxy_retry_count = 1
            self._stream_proxy_last_stall_recover_ts = now_mono
            self._load_start_ts = now_mono
            log.warning(
                "Detected stalled direct YouTube playback after %.1fs (state=%s, pos=%sms); retrying via local stream proxy",
                max(0.0, now_mono - load_started),
                state,
                int(cur_ms),
            )
            self._load_vlc_url(proxied, http_headers=self._last_vlc_http_headers)
        except Exception:
            pass

    def _load_vlc_url(
        self,
        final_url: str,
        load_seq: int | None = None,
        http_headers: dict | None = None,
    ) -> None:
        log.debug("load_vlc_url: %s", final_url)
        try:
            if load_seq is None:
                load_seq = int(getattr(self, '_active_load_seq', 0))
            else:
                load_seq = int(load_seq)
        except Exception:
            load_seq = 0
        try:
            self.player.stop()
        except Exception:
            pass
        try:
            if http_headers is not None:
                self._last_vlc_http_headers = dict(http_headers or {})
        except Exception:
            pass
        media = self.instance.media_new(final_url)
        try:
            effective_headers = dict(getattr(self, "_last_vlc_http_headers", None) or {})
            ua_value = (
                str(effective_headers.get("User-Agent") or effective_headers.get("user-agent") or "").strip()
                or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
            referer_value = str(
                effective_headers.get("Referer")
                or effective_headers.get("referer")
                or effective_headers.get("Referrer")
                or effective_headers.get("referrer")
                or ""
            ).strip()
            cookie_value = str(effective_headers.get("Cookie") or effective_headers.get("cookie") or "").strip()
            cache_ms = int(self.config_manager.get('vlc_network_caching_ms', 500))
            if cache_ms < 0: cache_ms = 0

            if isinstance(final_url, str) and final_url.startswith('http://127.0.0.1:') and '/media?id=' in final_url:
                cache_ms = int(self.config_manager.get('vlc_local_proxy_network_caching_ms', 50))
                if cache_ms < 0: cache_ms = 0
                file_cache_ms = int(self.config_manager.get('vlc_local_proxy_file_caching_ms', 50))
                if file_cache_ms < 0: file_cache_ms = 0
            else:
                file_cache_ms = max(500, cache_ms)

            log.debug("VLC options: network-caching=%s file-caching=%s", cache_ms, file_cache_ms)
            media.add_option(f':network-caching={cache_ms}')
            media.add_option(f':file-caching={file_cache_ms}')
            media.add_option(':http-reconnect')
            media.add_option(f':http-user-agent={ua_value}')
            if referer_value:
                media.add_option(f':http-referrer={referer_value}')
            if cookie_value:
                media.add_option(f':http-cookie={cookie_value}')
        except Exception:
            pass
        try:
            self.player.set_media(media)
        except OSError:
            log.exception("VLC set_media failed; reinitializing player")
            if not self._init_vlc():
                return
            try:
                self.player.set_media(media)
            except Exception:
                log.exception("VLC set_media failed after reinit")
                return
        def _do_play():
            try:
                if int(getattr(self, '_active_load_seq', 0)) != int(load_seq):
                    log.debug("_do_play aborted (stale seq)")
                    return
            except Exception as e:
                log.debug("Error checking load sequence in _do_play: %s", e)
            try:
                log.debug("Calling self.player.play()")
                self.player.play()
            except Exception:
                log.exception("Error calling self.player.play()")
                return
            try:
                self.apply_preferred_soundcard()
            except Exception:
                pass
            try:
                self.player.audio_set_volume(int(getattr(self, 'volume', 100)))
            except Exception:
                pass
            
            # Sync the volume slider with VLC's actual volume to prevent jumps on first adjustment
            try:
                wx.CallLater(500, self._sync_volume_from_vlc)
            except Exception:
                pass
            
            self.is_playing = True
            self._set_play_button_label(True)

        try:
            wx.CallLater(50, _do_play)
        except Exception:
            _do_play()

        try:
            desired = 2000
            try:
                if getattr(self, '_pending_resume_seek_ms', None) is not None:
                    desired = 250
            except Exception:
                desired = 2000
            # Run the timer faster when skip-silence is enabled so jumps feel snappier.
            try:
                if bool(self.config_manager.get("skip_silence", False)):
                    desired = min(desired, 280)
            except Exception:
                pass
            if (not self.timer.IsRunning()) or int(getattr(self, '_timer_interval_ms', 0) or 0) != int(desired):
                self.timer.Start(int(desired))
                self._timer_interval_ms = int(desired)
        except Exception:
            pass
        try:
            self.set_playback_speed(self.playback_speed)
        except Exception:
            pass

    def init_ui(self):
        panel = wx.Panel(self)
        self.panel = panel
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        # Title
        self.title_lbl = wx.StaticText(panel, label="No Track Loaded")
        sizer.Add(self.title_lbl, 0, wx.ALL | wx.CENTER, 5)

        # Status (helps screen readers during connect/buffer)
        self.status_lbl = wx.StaticText(panel, label="")
        self.status_lbl.SetName("Playback Status")
        sizer.Add(self.status_lbl, 0, wx.ALL | wx.CENTER, 2)
        
        # Slider
        self.slider = wx.Slider(panel, value=0, minValue=0, maxValue=1000)
        self.slider.SetName("Playback Position")
        # FIX: Separate tracking (dragging) from release (seeking)
        self.slider.Bind(wx.EVT_SCROLL_THUMBTRACK, self.on_slider_track)
        self.slider.Bind(wx.EVT_SCROLL_THUMBRELEASE, self.on_slider_release)
        # Also catch CLICK/CHANGED for non-drag clicks on the bar
        self.slider.Bind(wx.EVT_SCROLL_CHANGED, self.on_slider_release)
        
        sizer.Add(self.slider, 0, wx.EXPAND | wx.ALL, 5)
        
        # Time Labels
        time_sizer = wx.BoxSizer(wx.HORIZONTAL)
        self.current_time_lbl = wx.StaticText(panel, label="00:00")
        self.total_time_lbl = wx.StaticText(panel, label="00:00")
        time_sizer.Add(self.current_time_lbl, 0, wx.LEFT, 5)
        time_sizer.AddStretchSpacer()
        time_sizer.Add(self.total_time_lbl, 0, wx.RIGHT, 5)
        sizer.Add(time_sizer, 0, wx.EXPAND | wx.BOTTOM, 5)
        
        # Controls
        btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        
        # Rewind 10s
        rewind_btn = wx.Button(panel, label="-10s")
        rewind_btn.SetName("Rewind 10 seconds")
        rewind_btn.Bind(wx.EVT_BUTTON, self.on_rewind)
        btn_sizer.Add(rewind_btn, 0, wx.ALL, 5)
        
        # Play/Pause
        self.play_btn = wx.Button(panel, label="Play")
        self.play_btn.Bind(wx.EVT_BUTTON, self.on_play_pause)
        btn_sizer.Add(self.play_btn, 0, wx.ALL, 5)

        # Stop
        self.stop_btn = wx.Button(panel, label="Stop")
        self.stop_btn.Bind(wx.EVT_BUTTON, self.on_stop)
        btn_sizer.Add(self.stop_btn, 0, wx.ALL, 5)
        
        # Forward 10s
        forward_btn = wx.Button(panel, label="+10s")
        forward_btn.SetName("Fast Forward 10 seconds")
        forward_btn.Bind(wx.EVT_BUTTON, self.on_forward)
        btn_sizer.Add(forward_btn, 0, wx.ALL, 5)
        
        # Speed
        speeds = utils.build_playback_speeds()
        self.speed_combo = wx.ComboBox(panel, choices=[f"{s}x" for s in speeds], style=wx.CB_READONLY)
        self.speed_combo.SetName("Playback Speed")
        self.speed_combo.Bind(wx.EVT_COMBOBOX, self.on_speed_select)
        btn_sizer.Add(self.speed_combo, 0, wx.ALL, 5)
        
        # Cast
        self.cast_btn = wx.Button(panel, label="Cast")
        self.cast_btn.Bind(wx.EVT_BUTTON, self.on_cast)
        btn_sizer.Add(self.cast_btn, 0, wx.ALL, 5)

        # Chapters menu
        self.chapters_btn = wx.Button(panel, label="Chapters")
        self.chapters_btn.SetName("Chapters Menu")
        self.chapters_btn.Bind(wx.EVT_BUTTON, self.on_show_chapters_menu)
        btn_sizer.Add(self.chapters_btn, 0, wx.ALL, 5)
        
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER)

        # Volume
        volume_sizer = wx.BoxSizer(wx.HORIZONTAL)
        volume_lbl = wx.StaticText(panel, label="Volume")
        volume_sizer.Add(volume_lbl, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.volume_slider = wx.Slider(panel, value=int(getattr(self, "volume", 100)), minValue=0, maxValue=100, style=wx.SL_HORIZONTAL)
        self.volume_slider.SetName("Volume")
        self.volume_slider.Bind(wx.EVT_SCROLL_THUMBTRACK, self.on_volume_slider)
        self.volume_slider.Bind(wx.EVT_SCROLL_CHANGED, self.on_volume_slider)
        volume_sizer.Add(self.volume_slider, 1, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 6)
        self.volume_value_lbl = wx.StaticText(panel, label=f"{int(getattr(self, 'volume', 100))}%")
        volume_sizer.Add(self.volume_value_lbl, 0, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(volume_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 6)
        
        # Chapters
        self.chapter_choice = wx.ComboBox(panel, style=wx.CB_READONLY)
        self.chapter_choice.SetName("Chapters")
        self.chapter_choice.Bind(wx.EVT_COMBOBOX, self.on_chapter_select)
        if hasattr(wx, "EVT_COMBOBOX_CLOSEUP"):
            try:
                self.chapter_choice.Bind(wx.EVT_COMBOBOX_CLOSEUP, self.on_chapter_closeup)
                self._chapter_closeup_supported = True
            except Exception:
                self._chapter_closeup_supported = False
        sizer.Add(self.chapter_choice, 0, wx.EXPAND | wx.ALL, 5)
        
        panel.SetSizer(sizer)
        self._init_player_menu_bar()
        self._refresh_chapter_controls_state()

    def _init_player_menu_bar(self) -> None:
        try:
            menubar = wx.MenuBar()
            chapters_menu = wx.Menu()

            self._chapter_menu_show_item = chapters_menu.Append(wx.ID_ANY, "Show &Chapters\tCtrl+M")
            self._chapter_menu_prev_item = chapters_menu.Append(wx.ID_ANY, "&Previous Chapter\tCtrl+Shift+Left")
            self._chapter_menu_next_item = chapters_menu.Append(wx.ID_ANY, "&Next Chapter\tCtrl+Shift+Right")

            menubar.Append(chapters_menu, "&Chapters")
            self.SetMenuBar(menubar)

            self.Bind(wx.EVT_MENU, self.on_show_chapters_menu, self._chapter_menu_show_item)
            self.Bind(wx.EVT_MENU, self.on_prev_chapter, self._chapter_menu_prev_item)
            self.Bind(wx.EVT_MENU, self.on_next_chapter, self._chapter_menu_next_item)
        except Exception:
            log.exception("Failed to initialize player menu bar")
        finally:
            self._refresh_chapter_controls_state()

    def _refresh_chapter_controls_state(self) -> None:
        has_chapters = bool(getattr(self, "current_chapters", None))
        try:
            item = getattr(self, "_chapter_menu_prev_item", None)
            if item is not None:
                item.Enable(bool(has_chapters))
        except Exception:
            pass
        try:
            item = getattr(self, "_chapter_menu_next_item", None)
            if item is not None:
                item.Enable(bool(has_chapters))
        except Exception:
            pass

    def _active_chapter_index(self) -> int:
        try:
            idx = int(self.chapter_choice.GetSelection())
            if idx != wx.NOT_FOUND:
                return int(idx)
        except Exception:
            pass

        try:
            chapters = list(getattr(self, "current_chapters", []) or [])
            if not chapters:
                return -1
            cur_sec = float(self._current_position_ms()) / 1000.0
            active = -1
            for i, ch in enumerate(chapters):
                if cur_sec >= float(ch.get("start", 0) or 0):
                    active = i
                else:
                    break
            return int(active)
        except Exception:
            return -1

    def _format_chapter_menu_label(self, chapter: dict) -> str:
        try:
            start = float(chapter.get("start", 0) or 0)
        except Exception:
            start = 0.0
        if start < 0:
            start = 0.0
        mins = int(start // 60)
        secs = int(start % 60)
        title = str(chapter.get("title", "") or "").strip() or f"Chapter {mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}  {title}"

    def _jump_to_chapter_index(self, idx: int) -> None:
        try:
            chapters = list(getattr(self, "current_chapters", []) or [])
        except Exception:
            chapters = []
        if not chapters:
            return
        try:
            target_idx = int(idx)
        except Exception:
            return
        if target_idx < 0 or target_idx >= len(chapters):
            return
        try:
            self.chapter_choice.SetSelection(int(target_idx))
        except Exception:
            pass
        self._chapter_pending_idx = int(target_idx)
        self._commit_chapter_selection()

    def _show_chapters_popup_menu(self) -> None:
        menu = wx.Menu()
        try:
            chapters = list(getattr(self, "current_chapters", []) or [])
            if not chapters:
                empty_item = menu.Append(wx.ID_ANY, "No chapters available")
                empty_item.Enable(False)
            else:
                active_idx = self._active_chapter_index()
                for i, ch in enumerate(chapters):
                    label = self._format_chapter_menu_label(ch)
                    if int(i) == int(active_idx):
                        label = f"[Current] {label}"
                    item = menu.Append(wx.ID_ANY, label)
                    menu.Bind(wx.EVT_MENU, lambda evt, idx=i: self._jump_to_chapter_index(idx), item)
            self.PopupMenu(menu)
        finally:
            try:
                menu.Destroy()
            except Exception:
                pass

    def show_chapters_menu(self) -> None:
        self._show_chapters_popup_menu()

    def jump_to_chapter(self, idx: int) -> None:
        self._jump_to_chapter_index(int(idx))

    def get_active_chapter_index(self) -> int:
        return int(self._active_chapter_index())

    def prev_chapter(self) -> None:
        self.on_prev_chapter(None)

    def next_chapter(self) -> None:
        self.on_next_chapter(None)

    def on_show_chapters_menu(self, event) -> None:
        self._show_chapters_popup_menu()

    def on_prev_chapter(self, event) -> None:
        idx = self._active_chapter_index()
        if idx <= 0:
            return
        self._jump_to_chapter_index(int(idx) - 1)

    def on_next_chapter(self, event) -> None:
        idx = self._active_chapter_index()
        try:
            total = len(getattr(self, "current_chapters", []) or [])
        except Exception:
            total = 0
        if total <= 0:
            return
        if idx < 0:
            self._jump_to_chapter_index(0)
            return
        if idx >= (total - 1):
            return
        self._jump_to_chapter_index(int(idx) + 1)

    def on_cast(self, event):
        if self.is_casting:
            cast_pos_ms = None
            try:
                pos_sec = self.casting_manager.get_position()
                if pos_sec is not None:
                    cast_pos_ms = int(float(pos_sec) * 1000.0)
            except Exception:
                cast_pos_ms = None

            # Fallback if device returns nothing or 0 (likely buffering/glitch)
            if cast_pos_ms is None or cast_pos_ms == 0:
                try:
                    fallback = int(getattr(self, '_cast_last_pos_ms', 0) or 0)
                    if fallback > 0:
                        cast_pos_ms = fallback
                except Exception:
                    pass
            
            if cast_pos_ms is None:
                cast_pos_ms = 0

            cast_was_playing = bool(self.is_playing)

            try:
                self.casting_manager.disconnect()
            except Exception:
                pass

            self.is_casting = False
            try:
                self.cast_btn.SetLabel('Cast')
            except Exception:
                pass
            try:
                self.title_lbl.SetLabel(f"{self.current_title} (Local)")
            except Exception:
                pass
            try:
                # Stop remote playback so audio does not continue on the cast device.
                self.casting_manager.stop_playback()
            except Exception:
                pass

            if self.current_url:
                same_media = False
                try:
                    same_media = (getattr(self, '_cast_handoff_source_url', None) == self.current_url)
                except Exception:
                    same_media = False

                if same_media:
                    try:
                        if self._resume_local_from_cast(int(cast_pos_ms), bool(cast_was_playing)):
                            self._cast_handoff_source_url = None
                            return
                    except Exception:
                        pass

                self._pending_resume_seek_ms = max(0, int(cast_pos_ms))
                self._pending_resume_seek_attempts = 0
                self._pending_resume_paused = (not cast_was_playing)
                self.load_media(
                    self.current_url,
                    use_ytdlp=False,
                    chapters=self.current_chapters,
                    title=self.current_title,
                    article_id=getattr(self, "current_article_id", None),
                )
                self._cast_handoff_source_url = None
            return

        local_pos_ms = 0
        try:
            if getattr(self, '_seek_target_ms', None) is not None:
                local_pos_ms = int(self._seek_target_ms or 0)
            else:
                local_pos_ms = int(self._current_position_ms())
            if local_pos_ms < 0:
                local_pos_ms = 0
        except Exception:
            local_pos_ms = 0

        local_was_playing = bool(self.is_playing)
        self._cast_local_was_playing = local_was_playing
        self._cast_last_pos_ms = local_pos_ms

        dlg = CastDialog(self, self.casting_manager)
        try:
            if dlg.ShowModal() != wx.ID_OK:
                return
            device = dlg.selected_device
            if not device:
                return

            try:
                self.casting_manager.connect(device)
                self.is_casting = True
                self.cast_btn.SetLabel('Disconnect')
                self.title_lbl.SetLabel(f"{self.current_title} (Casting to {device.name})")

                if local_was_playing:
                    try:
                        self.player.pause()
                    except Exception:
                        pass
                else:
                    try:
                        self.player.set_pause(1)
                    except Exception:
                        pass

                if self.current_url:
                    start_sec = None
                    try:
                        if local_pos_ms and int(local_pos_ms) > 0:
                            start_sec = float(local_pos_ms) / 1000.0
                    except Exception:
                        start_sec = None
                    self._cast_handoff_source_url = self.current_url
                    self.casting_manager.play(self.current_url, self.current_title, content_type='audio/mpeg', start_time_seconds=start_sec)
                    if local_pos_ms > 0:
                        try:
                            self._cast_handoff_target_ms = int(local_pos_ms)
                            self._cast_handoff_attempts_left = 4
                            wx.CallLater(1200, self._cast_handoff_seek_tick)
                        except Exception:
                            pass

                    if not local_was_playing:
                        try:
                            self.casting_manager.pause()
                        except Exception:
                            pass
                        self.is_playing = False
            except Exception as e:
                wx.MessageBox(f"Connection failed: {e}", 'Error', wx.ICON_ERROR)
        finally:
            try:
                dlg.Destroy()
            except Exception:
                pass

    def _cast_handoff_seek_tick(self):
        try:
            if not bool(getattr(self, 'is_casting', False)):
                return
            target_ms = int(getattr(self, '_cast_handoff_target_ms', 0) or 0)
            if target_ms <= 0:
                return

            try:
                pos_sec = self.casting_manager.get_position()
                if pos_sec is not None:
                    cur_ms = int(float(pos_sec) * 1000.0)
                    self._cast_last_pos_ms = int(cur_ms)
                    if abs(int(cur_ms) - int(target_ms)) <= 2000:
                        return
            except Exception:
                pass

            try:
                self.casting_manager.seek(float(target_ms) / 1000.0)
            except Exception:
                pass

            try:
                left = int(getattr(self, '_cast_handoff_attempts_left', 0) or 0)
            except Exception:
                left = 0
            left -= 1
            self._cast_handoff_attempts_left = left
            if left > 0:
                wx.CallLater(1200, self._cast_handoff_seek_tick)
        except Exception:
            pass

    def _resume_local_from_cast(self, position_ms: int, was_playing: bool) -> bool:
        try:
            position_ms = max(0, int(position_ms))
        except Exception:
            position_ms = 0

        try:
            media_obj = None
            try:
                media_obj = self.player.get_media()
            except Exception:
                media_obj = None
            if media_obj is None:
                return False

            try:
                desired = 250
                if (not self.timer.IsRunning()) or int(getattr(self, '_timer_interval_ms', 0) or 0) != int(desired):
                    self.timer.Start(int(desired))
                    self._timer_interval_ms = int(desired)
            except Exception:
                pass

            try:
                self.player.play()
            except Exception:
                pass

            self._pending_resume_seek_ms = int(position_ms)
            self._pending_resume_seek_attempts = 0
            self._pending_resume_paused = (not bool(was_playing))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Silence skipping
    # ------------------------------------------------------------------

    def _cancel_silence_scan(self):
        try:
            if self._silence_scan_abort is not None:
                self._silence_scan_abort.set()
        except Exception:
            pass
        try:
            self._cancel_silence_skip_probes()
        except Exception:
            pass
        self._silence_scan_abort = None
        self._silence_scan_thread = None
        self._silence_ranges = []
        self._silence_scan_ready = False
        self._silence_skip_active_target = None
        self._silence_skip_last_idx = None
        self._silence_skip_last_target_ms = None
        self._silence_skip_last_seek_ts = 0.0
        self._silence_skip_floor_ms = 0
        self._silence_skip_reset_floor = False
        self._silence_skip_verify_until_ts = 0.0
        self._silence_skip_verify_target_ms = None
        self._silence_skip_verify_source_ms = None
        self._silence_skip_verify_attempted = False
        self._silence_scan_pending = False
        self._silence_scan_pending_info = None

    def _queue_silence_scan(self, url: str, load_seq: int, headers: dict | None = None) -> None:
        if not self.config_manager.get("skip_silence", False):
            return
        if not url or self.is_casting:
            return
        try:
            self._silence_scan_pending = True
            self._silence_scan_pending_info = (str(url), int(load_seq), dict(headers or {}))
        except Exception:
            self._silence_scan_pending = False
            self._silence_scan_pending_info = None

    def _maybe_start_pending_silence_scan(self, playing_now: bool) -> None:
        if not playing_now:
            return
        if self.is_casting:
            return
        try:
            if not bool(getattr(self, "_silence_scan_pending", False)):
                return
        except Exception:
            return

        try:
            delay_s = float(self.config_manager.get("silence_scan_delay_s", 4.0) or 4.0)
        except Exception:
            delay_s = 4.0
        try:
            if (time.monotonic() - float(getattr(self, "_load_start_ts", 0.0) or 0.0)) < float(delay_s):
                return
        except Exception:
            pass

        try:
            info = getattr(self, "_silence_scan_pending_info", None)
        except Exception:
            info = None
        if not info:
            self._silence_scan_pending = False
            self._silence_scan_pending_info = None
            return
        try:
            url, load_seq, headers = info
        except Exception:
            self._silence_scan_pending = False
            self._silence_scan_pending_info = None
            return
        try:
            if int(load_seq) != int(getattr(self, "_active_load_seq", 0) or 0):
                self._silence_scan_pending = False
                self._silence_scan_pending_info = None
                return
        except Exception:
            pass

        self._silence_scan_pending = False
        self._silence_scan_pending_info = None
        try:
            self._start_silence_scan(str(url), int(load_seq), headers=headers)
        except Exception:
            pass

    def _start_silence_scan(self, url: str, load_seq: int, headers: dict = None) -> None:
        if not self.config_manager.get("skip_silence", False):
            return
        if not url or self.is_casting:
            return
        try:
            self._silence_scan_ready = False
        except Exception:
            pass
        self._silence_scan_ready = False
        self._silence_ranges = []
        abort_evt = threading.Event()
        self._silence_scan_abort = abort_evt

        def _worker() -> None:
            try:
                try:
                    base_rate = int(self.config_manager.get("silence_scan_sample_rate", 16000) or 16000)
                except Exception:
                    base_rate = 16000
                try:
                    remote_rate = int(self.config_manager.get("silence_scan_remote_sample_rate", 8000) or 8000)
                except Exception:
                    remote_rate = 8000
                window_ms = int(self.config_manager.get("silence_skip_window_ms", 30) or 30)
                min_ms = int(self.config_manager.get("silence_skip_min_ms", 800) or 800)  # 800ms minimum to avoid speech pauses
                threshold_db = float(self.config_manager.get("silence_skip_threshold_db", -50.0) or -50.0)  # More lenient: -50 dB instead of -42 dB
                pad_ms = int(self.config_manager.get("silence_skip_padding_ms", 300) or 300)  # Increased padding from 200ms to 300ms for safety
                merge_gap = int(self.config_manager.get("silence_skip_merge_gap_ms", 200) or 200)  # Reduced from 300ms to 200ms to avoid over-merging
                vad_aggr = int(self.config_manager.get("silence_vad_aggressiveness", 1) or 1)  # Reduced from 2 to 1 (less aggressive)
                vad_frame_ms = int(self.config_manager.get("silence_vad_frame_ms", 30) or 30)
                try:
                    base_url = getattr(self, "current_url", "") or ""
                except Exception:
                    base_url = ""
                is_remote = base_url.startswith("http") and not ("127.0.0.1" in base_url or "localhost" in base_url)
                if is_remote:
                    # For remote streams, be even more conservative to avoid network-induced false positives
                    if int(vad_aggr) > 0:
                        vad_aggr = 0  # Least aggressive for remote
                    if float(threshold_db) > -52.0:
                        threshold_db = -52.0  # Even more lenient for remote
                    if int(min_ms) < 1200:
                        min_ms = 1200  # Much longer minimum for remote to avoid false positives
                    if int(merge_gap) > 200:
                        merge_gap = 200  # Keep regions separate for remote to avoid over-merging
                sample_rate = int(remote_rate) if is_remote else int(base_rate)
                try:
                    threads = int(self.config_manager.get("silence_scan_threads", 1 if is_remote else 2))
                except Exception:
                    threads = 1 if is_remote else 2
                try:
                    low_priority = bool(self.config_manager.get("silence_scan_low_priority", True))
                except Exception:
                    low_priority = True
                ranges = scan_audio_for_silence(
                    url,
                    sample_rate=sample_rate,
                    window_ms=window_ms,
                    min_silence_ms=min_ms,
                    threshold_db=threshold_db,
                    detection_mode="vad",
                    vad_aggressiveness=vad_aggr,
                    vad_frame_ms=vad_frame_ms,
                    merge_gap_ms=merge_gap,
                    abort_event=abort_evt,
                    headers=headers,
                    threads=threads,
                    low_priority=low_priority,
                )
                if abort_evt.is_set():
                    return
                padded = []
                for s, e in ranges:
                    start = max(0, int(s) - pad_ms)
                    end = int(e) + pad_ms
                    padded.append((start, end))
                merged = merge_ranges_with_gap(padded, gap_ms=merge_gap)
                if abort_evt.is_set() or int(getattr(self, "_active_load_seq", 0)) != int(load_seq):
                    return
                self._silence_ranges = merged
                self._silence_scan_ready = True
                log.debug("Silence scan ready (%s ranges)", len(merged))
            except Exception as e:
                log.debug("Silence scan failed: %s", e)
                self._silence_scan_ready = False

        try:
            t = threading.Thread(target=_worker, daemon=True)
            t.start()
            self._silence_scan_thread = t
        except Exception:
            pass

    def _cancel_silence_skip_probes(self) -> None:
        try:
            calllaters = list(getattr(self, "_silence_skip_probe_calllaters", []) or [])
        except Exception:
            calllaters = []
        for cl in calllaters:
            try:
                cl.Stop()
            except Exception:
                pass
        try:
            self._silence_skip_probe_calllaters = []
        except Exception:
            pass

    def _schedule_silence_skip_probes(self, target_ms: int, source_ms: int) -> None:
        try:
            self._cancel_silence_skip_probes()
        except Exception:
            pass
        try:
            seq = int(getattr(self, "_silence_skip_probe_seq", 0) or 0) + 1
        except Exception:
            seq = 1
        try:
            self._silence_skip_probe_seq = int(seq)
        except Exception:
            pass

        delays = (250, 650, 1200, 2500, 4000)
        for delay_ms in delays:
            try:
                cl = wx.CallLater(int(delay_ms), self._silence_skip_probe_tick, int(seq), int(delay_ms), int(target_ms), int(source_ms))
                self._silence_skip_probe_calllaters.append(cl)
            except Exception:
                pass

    def _silence_skip_probe_tick(self, seq: int, delay_ms: int, target_ms: int, source_ms: int) -> None:
        try:
            if int(seq) != int(getattr(self, "_silence_skip_probe_seq", 0) or 0):
                return
        except Exception:
            return
        try:
            cur = int(self.player.get_time() or 0)
        except Exception:
            cur = -1
        try:
            delta = int(target_ms) - int(cur)
        except Exception:
            delta = None
        try:
            state = self.player.get_state()
        except Exception:
            state = None
        try:
            playing = bool(self.player.is_playing())
        except Exception:
            playing = bool(getattr(self, "is_playing", False))
        try:
            seekable = self.player.is_seekable() if hasattr(self.player, "is_seekable") else None
        except Exception:
            seekable = None
        try:
            url = getattr(self, "current_url", "") or ""
        except Exception:
            url = ""
        is_remote = url.startswith("http") and not ("127.0.0.1" in url or "localhost" in url)
        log.info(
            "Silence skip probe t+%sms: cur=%s target=%s delta=%s source=%s state=%s playing=%s seekable=%s remote=%s",
            int(delay_ms),
            int(cur),
            int(target_ms),
            delta,
            int(source_ms),
            state,
            playing,
            seekable,
            is_remote,
        )

    def _start_http_seek_diagnostics(self, url: str, headers: dict | None = None) -> None:
        if not url:
            return
        try:
            parsed = urlparse(url)
        except Exception:
            return
        scheme = (parsed.scheme or "").lower()
        if scheme not in ("http", "https"):
            return
        host = (parsed.netloc or "").lower()
        if not host or host in ("127.0.0.1", "localhost"):
            return
        try:
            diag_headers = dict(headers or {})
        except Exception:
            diag_headers = {}

        def _worker() -> None:
            resp = None
            try:
                req_headers = dict(diag_headers)
                req_headers["Range"] = "bytes=0-1"
                resp = utils.safe_requests_get(url, headers=req_headers, stream=True, timeout=10, allow_redirects=True)
                status = int(getattr(resp, "status_code", 0) or 0)
                hdrs = getattr(resp, "headers", {}) or {}
                accept_ranges = str(hdrs.get("Accept-Ranges", "") or "")
                content_range = str(hdrs.get("Content-Range", "") or "")
                content_type = str(hdrs.get("Content-Type", "") or "")
                content_len = str(hdrs.get("Content-Length", "") or "")
                final_url = str(getattr(resp, "url", "") or "")
                low = (final_url or url).lower()
                is_hls = ".m3u8" in low or "mpegurl" in content_type.lower()
                log.info(
                    "HTTP seek probe: url=%s final=%s status=%s accept_ranges=%s content_range=%s content_type=%s content_length=%s hls=%s",
                    url,
                    final_url,
                    status,
                    accept_ranges,
                    content_range,
                    content_type,
                    content_len,
                    is_hls,
                )
            except Exception as e:
                log.info("HTTP seek probe failed: url=%s err=%s", url, e)
            finally:
                try:
                    if resp is not None:
                        resp.close()
                except Exception:
                    pass

        try:
            threading.Thread(target=_worker, daemon=True).start()
        except Exception:
            pass

    def _maybe_skip_silence(self, pos_ms: int) -> None:
        if not self.config_manager.get("skip_silence", False):
            return
        if self.is_casting:
            return
        try:
            if hasattr(self.player, "is_seekable") and (self.player.is_seekable() is False):
                return
        except Exception:
            pass
        try:
            if getattr(self, "_pending_resume_seek_ms", None) is not None:
                return
        except Exception:
            pass
        try:
            if bool(getattr(self, "_resume_restore_inflight", False)):
                return
        except Exception:
            pass
        if not bool(getattr(self, "_silence_scan_ready", False)):
            return
        if not getattr(self, "_silence_ranges", None):
            return
        
        now = time.monotonic()
        try:
            pause_until = float(getattr(self, "_silence_skip_pause_until_ts", 0.0) or 0.0)
            if now < pause_until:
                return
        except Exception:
            pass
        if getattr(self, "_is_dragging_slider", False):
            return
        try:
            floor = int(getattr(self, "_silence_skip_floor_ms", 0) or 0)
            if int(pos_ms) + 500 < int(floor):
                return
        except Exception:
            pass

        # 1. Much longer cooldown for remote streams (YouTube DASH is jittery)
        url = getattr(self, "current_url", "") or ""
        is_remote = url.startswith("http") and not ("127.0.0.1" in url or "localhost" in url)
        
        cooldown = 5.0 if is_remote else 2.5
        
        try:
            last_jump_ts = float(getattr(self, "_silence_skip_last_ts", 0.0) or 0.0)
            if now - last_jump_ts < cooldown:
                return
        except Exception:
            pass

        try:
            current_target = getattr(self, "_silence_skip_active_target", None)
        except Exception:
            current_target = None

        # 2. Cushion past silence (configurable; keep remote conservative).
        try:
            resume_backoff = int(self.config_manager.get("silence_skip_resume_backoff_ms", 1000) or 1000)
        except Exception:
            resume_backoff = 1000
        if resume_backoff < 0:
            resume_backoff = 0
        if is_remote and resume_backoff > 1000:
            resume_backoff = 1000
        try:
            retrigger_backoff = int(self.config_manager.get("silence_skip_retrigger_backoff_ms", 1400) or 1400)
        except Exception:
            retrigger_backoff = 1400
        try:
            floor = int(getattr(self, "_silence_skip_floor_ms", 0) or 0)
        except Exception:
            floor = 0
        
        for idx, (start, end) in enumerate(self._silence_ranges):
            if pos_ms < start - 1000:
                # Ranges are sorted; no need to continue.
                break
            
            # If we are currently inside a silent span...
            if start - 100 <= pos_ms <= end - 100:
                target_ms = int(end) + resume_backoff
                if int(target_ms) < int(floor):
                    return
                
                # 3. Robust landing verification:
                # If we just tried to jump to this exact target, don't loop!
                try:
                    last_target = getattr(self, "_silence_skip_last_target_ms", None)
                    if last_target is not None and abs(int(last_target) - int(target_ms)) <= 1000:
                        return
                except Exception:
                    pass

                try:
                    self._silence_skip_active_target = int(target_ms)
                    self._silence_skip_last_ts = float(now)
                    self._silence_skip_last_idx = int(idx)
                    self._silence_skip_last_target_ms = int(target_ms)
                    self._silence_skip_last_seek_ts = float(now)
                    self._silence_skip_verify_until_ts = float(now) + (5.0 if is_remote else 3.0)
                    self._silence_skip_verify_target_ms = int(target_ms)
                    self._silence_skip_verify_source_ms = int(pos_ms)
                    self._silence_skip_verify_attempted = False
                    _log(f"Skipping silence: {pos_ms}ms -> {target_ms}ms")
                except Exception:
                    pass

                try:
                    self._schedule_silence_skip_probes(int(target_ms), int(pos_ms))
                except Exception:
                    pass
                
                # Seek immediately
                self._apply_seek_time_ms(int(target_ms), force=True, reason="silence_skip")
                return

        try:
            if current_target is not None and pos_ms > int(current_target) + 500:
                self._silence_skip_active_target = None
            if self._silence_skip_last_idx is not None:
                last_idx = int(self._silence_skip_last_idx)
                if last_idx < len(self._silence_ranges):
                    _, last_end = self._silence_ranges[last_idx]
                    if pos_ms > last_end + retrigger_backoff + 300:
                        self._silence_skip_last_idx = None
            if self._silence_skip_last_target_ms is not None and (now - float(getattr(self, "_silence_skip_last_seek_ts", 0.0) or 0.0)) > 2.0:
                if abs(pos_ms - int(self._silence_skip_last_target_ms)) > retrigger_backoff:
                    self._silence_skip_last_target_ms = None
        except Exception:
            pass

    def _maybe_range_cache_url(self, url: str, headers: dict | None = None, url_is_resolved: bool = False) -> str:
        try:
            if not url:
                return url
            self._last_orig_url = url
            self._last_used_range_proxy = False
            self._last_used_stream_proxy = False
            self._last_range_proxy_headers = headers or {}
            self._last_range_proxy_cache_dir = None
            self._last_range_proxy_prefetch_kb = None
            self._last_range_proxy_initial_burst_kb = None
            self._last_range_proxy_initial_inline_kb = None
            self._last_vlc_url = url
            self._range_proxy_retry_count = 0
            self._stream_proxy_retry_count = 0
            low = url.lower()
            if not (low.startswith('http://') or low.startswith('https://')):
                return url
            try:
                parsed = urlparse(url)
                host = (parsed.netloc or "").lower()
                host_name = (parsed.hostname or "").lower()
            except Exception:
                host = ""
                host_name = ""
            if host_name in ("127.0.0.1", "localhost"):
                return url
            # YouTube direct media URLs (googlevideo CDN) can be sensitive to
            # proxying in packaged builds; prefer direct VLC playback.
            if _is_googlevideo_url(url):
                return url
            # HLS playlists often contain relative segment URLs; proxying them through
            # the range cache breaks resolution and also isn't helpful for caching.
            if ".m3u8" in low:
                return url
            force_proxy = False
            try:
                force_proxy = bool(self.config_manager.get("skip_silence", False))
            except Exception:
                force_proxy = False
            if not force_proxy:
                if not bool(self.config_manager.get('range_cache_enabled', True)):
                    return url
                apply_all = bool(self.config_manager.get('range_cache_apply_all_hosts', True))
                hosts = self.config_manager.get('range_cache_hosts', []) or []
                try:
                    if any(str(h).strip() in ('*', 'all', 'ALL') for h in hosts):
                        apply_all = True
                except Exception:
                    pass
                if not apply_all:
                    if not host or not hosts:
                        return url
                    host_ok = False
                    for h in hosts:
                        try:
                            hs = str(h).strip().lower()
                        except Exception:
                            continue
                        if not hs:
                            continue
                        if hs.startswith('*.') and host.endswith(hs[1:]):
                            host_ok = True
                            break
                        if host == hs or host.endswith('.' + hs):
                            host_ok = True
                            break
                        if hs in host:
                            host_ok = True
                            break
                    if not host_ok:
                        return url
            cache_dir = self.config_manager.get('range_cache_dir', '') or None
            prefetch_kb = int(self.config_manager.get('range_cache_prefetch_kb', 16384) or 16384)
            inline_window_kb = int(self.config_manager.get('range_cache_inline_window_kb', 1024) or 1024)
            background_download = bool(self.config_manager.get('range_cache_background_download', True))
            background_chunk_kb = int(self.config_manager.get('range_cache_background_chunk_kb', 8192) or 8192)
            initial_burst_kb = int(self.config_manager.get('range_cache_initial_burst_kb', 65536) or 65536)
            initial_inline_kb = int(self.config_manager.get('range_cache_initial_inline_prefetch_kb', 1024) or 1024)
            proxy = get_range_cache_proxy(cache_dir=cache_dir if cache_dir else None, prefetch_kb=prefetch_kb,
                                         background_download=background_download, background_chunk_kb=background_chunk_kb,
                                         inline_window_kb=inline_window_kb,
                                         initial_burst_kb=initial_burst_kb,
                                         initial_inline_prefetch_kb=initial_inline_kb,
                                         debug_logs=bool(self.config_manager.get('range_cache_debug', False)))
            
            # Default headers
            req_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            }
            # Merge with passed headers (e.g. from yt-dlp)
            if headers:
                req_headers.update(headers)

            if 'promodj.com' in host:
                req_headers['Referer'] = 'https://promodj.com/'
            
            self._last_used_range_proxy = True
            self._last_range_proxy_headers = dict(req_headers)
            self._last_range_proxy_cache_dir = cache_dir if cache_dir else None
            self._last_range_proxy_prefetch_kb = prefetch_kb
            self._last_range_proxy_initial_burst_kb = initial_burst_kb
            self._last_range_proxy_initial_inline_kb = initial_inline_kb
            
            proxied = proxy.proxify(url, headers=req_headers, skip_redirect_resolve=url_is_resolved)
            log.debug("Proxy URL generated: %s (skip_redirect_resolve=%s)", proxied, url_is_resolved)
            try:
                if hasattr(proxy, "is_ready") and (proxy.is_ready() is False):
                    log.debug("Proxy not ready yet; proceeding without blocking")
            except Exception as e:
                log.debug("Proxy connection check error: %s", e)
                pass
            
            log.debug("Proxy connection verified; using proxy")
            self._last_vlc_url = proxied
            return proxied
        except Exception as e:
            log.debug("_maybe_range_cache_url exception: %s", e)
            return url

    def _handle_media_load_error(self, load_seq: int, url: str, error_msg: str | None = None, open_browser: bool = False) -> None:
        try:
            if int(load_seq) != int(getattr(self, "_active_load_seq", 0) or 0):
                return
        except Exception:
            return
        try:
            if error_msg:
                _log(str(error_msg))
        except Exception:
            pass
        try:
            self._set_status("Failed to load media")
        except Exception:
            pass
        if open_browser and url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
        try:
            self.Close()
        except Exception:
            pass

    def _resolve_media_worker(
        self,
        load_seq: int,
        url: str,
        use_ytdlp: bool,
        title: str | None,
        chapters,
    ) -> None:
        final_url = url
        ytdlp_headers = {}
        resolved_title = title or "Playing Audio..."
        should_resolve = True

        if use_ytdlp:
            rumble_handled = False
            try:
                from core import rumble as rumble_mod

                if rumble_mod.is_rumble_url(url):
                    resolved = rumble_mod.resolve_rumble_media(url)
                    final_url = resolved.media_url
                    ytdlp_headers = resolved.headers or {}
                    resolved_title = resolved.title or title or "Media Stream"
                    rumble_handled = True
            except Exception as e:
                try:
                    _log(f"Rumble resolve failed: {e}")
                except Exception:
                    pass

            if not rumble_handled:
                try:
                    import yt_dlp
                    from core.dependency_check import _get_startup_info

                    class _YtdlpQuietLogger:
                        def __init__(self):
                            self.errors = []

                        def debug(self, msg):
                            return

                        def warning(self, msg):
                            return

                        def error(self, msg):
                            try:
                                self.errors.append(str(msg))
                            except Exception:
                                pass

                    ytdlp_logger = _YtdlpQuietLogger()

                    # Resolve a direct media URL via yt-dlp. We intentionally try
                    # *without* browser cookies first to avoid Windows cookie/DPAPI
                    # issues and reduce noisy stderr output.
                    parsed_url = None
                    try:
                        parsed_url = urlparse(url)
                    except Exception:
                        parsed_url = None
                    origin = None
                    try:
                        if parsed_url and parsed_url.scheme and parsed_url.netloc:
                            origin = f"{parsed_url.scheme}://{parsed_url.netloc}"
                    except Exception:
                        origin = None
                    ytdlp_headers = {
                        "User-Agent": utils.HEADERS.get("User-Agent", ""),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                        "Accept-Language": "en-US,en;q=0.9",
                    }
                    if origin:
                        ytdlp_headers["Origin"] = origin

                    base_opts = {
                        'format': _YTDLP_VLC_AUDIO_FORMAT,
                        'quiet': True,
                        'no_warnings': True,
                        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                        'referer': url,
                        'noprogress': True,
                        'color': 'never',
                        'logger': ytdlp_logger,
                        'http_headers': ytdlp_headers,
                        'geo_bypass': True,
                        'extractor_args': {
                            'youtube': {
                                'player_client': ['android_vr', 'android'],
                            }
                        },
                    }
                    if platform.system().lower() == "windows":
                        # Hide internal yt-dlp subprocess windows (ffmpeg/ffprobe)
                        base_opts['subprocess_startupinfo'] = _get_startup_info()

                    def _extract_with_opts(opts):
                        with yt_dlp.YoutubeDL(opts) as ydl:
                            return ydl.extract_info(url, download=False)

                    info = None
                    last_err = None
                    base_err = None
                    dpapi_cookie_err = None
                    skip_cookie_attempts = False
                    tried_cookie_sources = []
                    cookie_sources = list(discovery.get_ytdlp_cookie_sources(url) or [])
                    if bool(getattr(self, "_ytdlp_browser_cookies_dpapi_unavailable", False)):
                        if cookie_sources and not bool(getattr(self, "_ytdlp_browser_cookies_dpapi_notice_shown", False)):
                            try:
                                _log("yt-dlp browser cookies disabled for this session after a Windows DPAPI cookie decryption failure")
                            except Exception:
                                pass
                            try:
                                self._ytdlp_browser_cookies_dpapi_notice_shown = True
                            except Exception:
                                pass
                        cookie_sources = []
                    prefer_cookies = False
                    try:
                        if parsed_url and parsed_url.netloc:
                            prefer_cookies = "bloomberg.com" in parsed_url.netloc.lower()
                    except Exception:
                        prefer_cookies = False

                    attempts = []
                    if prefer_cookies and cookie_sources:
                        for source in cookie_sources:
                            attempts.append(("cookies", source))
                        attempts.append(("base", None))
                    else:
                        attempts.append(("base", None))
                        for source in cookie_sources:
                            attempts.append(("cookies", source))

                    for kind, source in attempts:
                        if kind == "cookies" and skip_cookie_attempts:
                            continue
                        opts = dict(base_opts)
                        if kind == "cookies" and source:
                            if source in tried_cookie_sources:
                                continue
                            tried_cookie_sources.append(source)
                            opts["cookiesfrombrowser"] = source
                        try:
                            info = _extract_with_opts(opts)
                            if kind == "cookies" and source:
                                _log(f"yt-dlp cookies OK ({source[0]})")
                            break
                        except Exception as e:
                            last_err = e
                            if kind == "base":
                                base_err = e
                            if kind == "cookies" and source:
                                if _is_ytdlp_dpapi_cookie_error(e):
                                    dpapi_cookie_err = e
                                    skip_cookie_attempts = True
                                    try:
                                        self._ytdlp_browser_cookies_dpapi_unavailable = True
                                        self._ytdlp_browser_cookies_dpapi_notice_shown = True
                                    except Exception:
                                        pass
                                    try:
                                        _log(
                                            f"yt-dlp cookies failed ({source[0]}): Windows DPAPI decryption unavailable; "
                                            "skipping remaining browser cookie attempts this session"
                                        )
                                    except Exception:
                                        pass
                                elif _is_ytdlp_cookie_load_error(e):
                                    _log(f"yt-dlp cookies failed ({source[0]}): cookie loading failed")
                                else:
                                    _log(f"yt-dlp cookies failed ({source[0]})")

                    if info is None:
                        cli_last_err = None
                        cli_base_err = None
                        cli_dpapi_err = None
                        cli_skip_cookie_attempts = bool(skip_cookie_attempts)
                        try:
                            cli_timeout_s = int(
                                max(
                                    10,
                                    min(
                                        120,
                                        float(self.config_manager.get("playback_resolve_timeout_s", 4.0) or 4.0) * 8.0,
                                    ),
                                )
                            )
                        except Exception:
                            cli_timeout_s = 30

                        # Frozen builds can keep an up-to-date yt-dlp CLI on disk between releases.
                        # Try it before failing when embedded Python yt_dlp extraction breaks.
                        for kind, source in attempts:
                            if kind == "cookies" and cli_skip_cookie_attempts:
                                continue
                            cli_source = source if kind == "cookies" else None
                            try:
                                info = _extract_ytdlp_info_via_cli(
                                    url,
                                    headers=ytdlp_headers,
                                    cookie_source=cli_source,
                                    timeout_s=cli_timeout_s,
                                )
                                if kind == "cookies" and source:
                                    _log(f"yt-dlp CLI cookies OK ({source[0]})")
                                _log("yt-dlp resolved via CLI fallback")
                                break
                            except Exception as cli_e:
                                cli_last_err = cli_e
                                if kind == "base":
                                    cli_base_err = cli_e
                                if kind == "cookies" and source:
                                    if _is_ytdlp_dpapi_cookie_error(cli_e):
                                        cli_dpapi_err = cli_e
                                        cli_skip_cookie_attempts = True
                                        try:
                                            self._ytdlp_browser_cookies_dpapi_unavailable = True
                                            self._ytdlp_browser_cookies_dpapi_notice_shown = True
                                        except Exception:
                                            pass
                                        try:
                                            _log(
                                                f"yt-dlp CLI cookies failed ({source[0]}): Windows DPAPI decryption unavailable; "
                                                "skipping remaining browser cookie attempts this session"
                                            )
                                        except Exception:
                                            pass
                                    elif _is_ytdlp_cookie_load_error(cli_e):
                                        _log(f"yt-dlp CLI cookies failed ({source[0]}): cookie loading failed")
                                    else:
                                        _log(f"yt-dlp CLI cookies failed ({source[0]})")

                        if info is None:
                            if dpapi_cookie_err is None and cli_dpapi_err is not None:
                                dpapi_cookie_err = cli_dpapi_err
                            if base_err is None and cli_base_err is not None:
                                base_err = cli_base_err
                            if cli_last_err is not None and last_err is None:
                                last_err = cli_last_err

                    if info is None:
                        rokfin_probe = None
                        is_rokfin_url = False
                        try:
                            if parsed_url and parsed_url.netloc:
                                is_rokfin_url = "rokfin.com" in parsed_url.netloc.lower()
                        except Exception:
                            is_rokfin_url = False

                        if is_rokfin_url:
                            try:
                                rokfin_probe = discovery.probe_rokfin_public_playback(url, timeout=12)
                            except Exception:
                                rokfin_probe = None
                            if isinstance(rokfin_probe, dict) and bool(rokfin_probe.get("ok")):
                                rk_media_url = str(rokfin_probe.get("media_url") or "").strip()
                                if rk_media_url:
                                    info = {
                                        "url": rk_media_url,
                                        "http_headers": dict(rokfin_probe.get("http_headers") or {}),
                                        "title": str(rokfin_probe.get("title") or title or "Media Stream"),
                                    }
                                    try:
                                        _log("Rokfin playback resolved via public API fallback")
                                    except Exception:
                                        pass

                        if info is None and isinstance(rokfin_probe, dict):
                            rk_reason = str(rokfin_probe.get("reason") or "").strip().lower()
                            if rk_reason == "auth_required":
                                raise RuntimeError(
                                    "Rokfin playback requires a Rokfin login/cookies for this post"
                                )
                            if rk_reason == "invalid_playback_id":
                                raise RuntimeError(
                                    "Rokfin playback is broken on the source site (invalid playback ID)"
                                )
                            if rk_reason == "no_content_url":
                                raise RuntimeError(
                                    "Rokfin did not provide a playable stream URL for this post"
                                )

                        if dpapi_cookie_err is not None and base_err is not None:
                            raise RuntimeError(
                                f"{base_err} (browser cookies unavailable on this Windows session: DPAPI decryption failed)"
                            )
                        raise last_err or RuntimeError("yt-dlp extraction failed")

                    # Handle playlists/multi-video pages
                    if 'entries' in info:
                        entries = list(info['entries'])
                        if entries:
                            info = entries[0]

                    final_url = info.get('url')
                    if not final_url:
                        raise RuntimeError("No media URL found in yt-dlp info")

                    ytdlp_headers = info.get('http_headers', {})
                    resolved_title = info.get('title', title or 'Media Stream')
                except Exception as e:
                    err_text = str(e or "")
                    err_lower = err_text.lower()
                    if "rokfin playback is broken on the source site" in err_lower or "rokfin playback requires a rokfin login/cookies" in err_lower:
                        log.warning("yt-dlp resolve failed (Rokfin): %s", err_text)
                    elif _is_ytdlp_dpapi_cookie_error(err_text) or "browser cookies unavailable on this windows session" in err_lower:
                        log.warning("yt-dlp resolve failed (browser cookies/DPAPI): %s", err_text)
                    else:
                        log.exception("yt-dlp resolve failed")
                    ui_msg = f"yt-dlp resolve failed: {e}"
                    if "rokfin playback is broken on the source site" in err_lower:
                        ui_msg = (
                            "Rokfin post is listed but not streamable right now: Rokfin returned an invalid "
                            "playback ID for this post."
                        )
                    elif "rokfin playback requires a rokfin login/cookies" in err_lower:
                        ui_msg = (
                            "Rokfin post is not anonymously streamable right now. Rokfin requires a login/cookies "
                            "to play this post."
                        )
                    elif "browser cookies unavailable on this windows session" in err_lower:
                        ui_msg = (
                            "yt-dlp resolve failed: this media may require a login, but browser cookies could not be "
                            "loaded on this Windows session (DPAPI). Try running BlindRSS as your normal Windows user "
                            "and restart the app."
                        )
                    wx.CallAfter(self._handle_media_load_error, int(load_seq), url, ui_msg, True)
                    return
        else:
            resolved_title = title or "Playing Audio..."
            try:
                maxr = int(self.config_manager.get('http_max_redirects', 30))
            except Exception:
                maxr = 30
            should_resolve = True
            try:
                low = str(final_url or "").lower()
                if low:
                    try:
                        path = urlparse(low).path or low
                    except Exception:
                        path = low
                    # Only skip redirect resolution for local files or already-proxied URLs
                    # Podcast tracking URLs (op3.dev, etc.) need resolution even if they end in .mp3
                    if path.endswith(_SEEKABLE_EXTENSIONS):
                        # Check if this looks like a tracking/redirect URL that needs resolution
                        try:
                            parsed = urlparse(low)
                            host = (parsed.netloc or "").lower()
                            # Known podcast tracking/analytics hosts that always redirect
                            tracking_hosts = ("op3.dev", "pdst.fm", "chrt.fm", "chtbl.com", "podtrac.com", 
                                            "blubrry.com", "podcasts.apple.com", "anchor.fm", "spotify.com")
                            if any(th in host for th in tracking_hosts):
                                should_resolve = True
                            else:
                                should_resolve = False
                        except Exception:
                            should_resolve = False
            except Exception:
                should_resolve = True

            try:
                if should_resolve and bool(self.config_manager.get("skip_silence", False)):
                    # When skip-silence is enabled, playback is forced through the local range-cache proxy,
                    # which can follow redirects. Avoid blocking startup on a pre-resolve round-trip.
                    if low.startswith("http") and ".m3u8" not in low:
                        should_resolve = False
            except Exception:
                pass

            if should_resolve:
                try:
                    resolve_timeout_s = float(self.config_manager.get("playback_resolve_timeout_s", 4.0) or 4.0)
                except Exception:
                    resolve_timeout_s = 4.0
                final_url = utils.resolve_final_url(final_url, max_redirects=maxr, timeout_s=resolve_timeout_s)
            final_url = utils.normalize_url_for_vlc(final_url)

        try:
            if int(load_seq) != int(getattr(self, "_active_load_seq", 0) or 0):
                return
        except Exception:
            return

        try:
            wx.CallAfter(
                self._finish_media_load,
                int(load_seq),
                url,
                final_url,
                dict(ytdlp_headers or {}),
                resolved_title,
                chapters,
                bool(use_ytdlp),
                bool(should_resolve),  # url_is_resolved: True if we already resolved redirects
            )
        except Exception:
            pass

    def _finish_media_load(
        self,
        load_seq: int,
        input_url: str,
        final_url: str,
        ytdlp_headers: dict,
        resolved_title: str,
        chapters,
        use_ytdlp: bool,
        url_is_resolved: bool = False,
    ) -> None:
        try:
            if int(load_seq) != int(getattr(self, "_active_load_seq", 0) or 0):
                return
        except Exception:
            return

        try:
            self.current_title = resolved_title or "Playing Audio..."
        except Exception:
            self.current_title = "Playing Audio..."
        try:
            self.title_lbl.SetLabel(self.current_title)
        except Exception:
            pass

        # Apply local resume state (if any) before starting playback.
        try:
            primary_resume_id = self._get_resume_id()
            fallback_resume_id = self._resume_fallback_id

            if primary_resume_id:
                self._maybe_restore_playback_position(str(primary_resume_id), self.current_title)

            if (
                getattr(self, "_pending_resume_seek_ms", None) is None
                and fallback_resume_id
                and str(fallback_resume_id) != str(primary_resume_id or "")
            ):
                self._maybe_restore_playback_position(str(fallback_resume_id), self.current_title)

                # Opportunistically migrate URL-keyed state to the primary id.
                try:
                    if (
                        primary_resume_id
                        and str(getattr(self, "_resume_restore_id", None) or "") == str(fallback_resume_id)
                        and str(primary_resume_id) != str(fallback_resume_id)
                    ):
                        st = self._get_playback_state_cached(str(fallback_resume_id))
                        if st is not None:
                            pos_ms = int(getattr(st, "position_ms", 0) or 0)
                            dur_ms = getattr(st, "duration_ms", None)
                            completed = bool(getattr(st, "completed", False))
                            seek_supported = None  # Let seekability be re-detected for the new key.

                            self._save_playback_state(
                                str(primary_resume_id),
                                pos_ms,
                                dur_ms,
                                self.current_title,
                                completed,
                                seek_supported=seek_supported,
                            )
                except Exception:
                    log.exception("Failed to migrate playback state")
        except Exception:
            log.exception("Error during playback position restore and migration")

        if self.is_casting:
            try:
                start_ms = getattr(self, "_pending_resume_seek_ms", None)
            except Exception:
                start_ms = None
            if start_ms is not None and int(start_ms) > 0:
                try:
                    self._cast_last_pos_ms = int(start_ms)
                except Exception:
                    pass
                self.casting_manager.play(
                    final_url,
                    self.current_title,
                    content_type="audio/mpeg",
                    start_time_seconds=float(int(start_ms)) / 1000.0,
                )
            else:
                self.casting_manager.play(final_url, self.current_title, content_type="audio/mpeg")
            self.is_playing = True
            self._set_status("Playing")
        else:
            try:
                low = str(final_url or "").lower()
                is_hls_hint = ".m3u8" in low
                log.info(
                    "Media resolved: input=%s final=%s ytdlp=%s hls_hint=%s",
                    input_url,
                    final_url,
                    bool(use_ytdlp),
                    bool(is_hls_hint),
                )
            except Exception:
                pass
            try:
                if bool(self.config_manager.get("debug_mode", False)):
                    self._start_http_seek_diagnostics(str(final_url), headers=ytdlp_headers)
            except Exception:
                pass
            final_url = self._maybe_range_cache_url(final_url, headers=ytdlp_headers, url_is_resolved=url_is_resolved)
            try:
                # Frozen Windows builds can fail on direct HTTPS googlevideo URLs
                # with certain bundled VLC/libvlc combinations. Route through the
                # local HTTP stream proxy up-front for these URLs.
                if _should_force_local_stream_proxy(
                    final_url,
                    is_frozen=bool(getattr(sys, "frozen", False)),
                ):
                    final_url = self._maybe_stream_proxy_url(final_url, headers=ytdlp_headers)
            except Exception:
                pass
            try:
                proxied = bool(self._last_used_range_proxy or self._last_used_stream_proxy)
                log.info(
                    "VLC URL: %s proxied=%s range_proxy=%s stream_proxy=%s",
                    final_url,
                    proxied,
                    bool(self._last_used_range_proxy),
                    bool(self._last_used_stream_proxy),
                )
            except Exception:
                pass
            self._last_load_chapters = chapters
            self._last_load_title = self.current_title
            self._queue_silence_scan(final_url, int(getattr(self, "_active_load_seq", 0)), headers=ytdlp_headers)
            self._set_status("Buffering...")
            self._load_vlc_url(
                final_url,
                load_seq=int(getattr(self, "_active_load_seq", 0)),
                http_headers=dict(ytdlp_headers or {}),
            )

        if chapters:
            self.update_chapters(chapters)

    def load_media(self, url, use_ytdlp=False, chapters=None, title=None, article_id=None):
        if not self.is_casting:
            if not self._ensure_vlc_ready():
                wx.MessageBox("VLC is not initialized. Playback is unavailable.", "Error", wx.OK | wx.ICON_ERROR)
                return
        _log(f"load_media: {url} (ytdlp={use_ytdlp})")
        log.debug("load_media url=%s is_casting=%s", url, self.is_casting)
        if not url:
            return
        try:
            self._current_use_ytdlp = bool(use_ytdlp)
        except Exception:
            self._current_use_ytdlp = False

        try:
            if article_id is not None:
                self.current_article_id = str(article_id)
            else:
                self.current_article_id = None
        except Exception:
            log.exception("Error updating current_article_id")
            self.current_article_id = None

        # Persist the previous item's position before switching to the new one.
        try:
            self._persist_playback_position(force=True)
        except Exception:
            log.exception("Failed to persist playback position on media load")
        try:
            self._cancel_scheduled_resume_save()
            self._stop_calllater("_seek_apply_calllater", "Error handling seek apply calllater on media load")
        except Exception:
            log.exception("Error during media load cleanup")
        finally:
            self._stopped_needs_resume = False
            
        self.current_url = url
        try:
            self._set_resume_ids(str(url), article_id)
        except Exception:
            log.exception("Failed to set resume IDs, falling back to URL-based ID")
            self._resume_id = str(url)
            self._resume_fallback_id = None
        self._resume_restore_inflight = False
        self._resume_restore_id = None
        self._resume_restore_target_ms = None
        try:
            self._pending_resume_seek_ms = None
            self._pending_resume_seek_attempts = 0
            self._pending_resume_paused = False
        except Exception:
            pass
        try:
            self._load_seq += 1
            self._active_load_seq = self._load_seq
        except Exception:
            pass
        self._cancel_silence_scan()

        try:
            self._pos_ms = 0
            self._pos_ts = time.monotonic()
            self._pos_allow_backwards_until_ts = 0.0
            self._pos_last_timer_ts = 0.0
            self._last_vlc_time_ms = 0
            self._seek_target_ms = None
            self._seek_target_ts = 0.0
        except Exception:
            pass
        try:
            self._seek_guard_target_ms = None
            self._seek_guard_attempts_left = 0
            self._seek_guard_reapply_left = 0
            if getattr(self, '_seek_guard_calllater', None) is not None:
                try:
                    self._seek_guard_calllater.Stop()
                except Exception:
                    pass
                self._seek_guard_calllater = None
        except Exception:
            pass
        
        self.slider.SetValue(0)
        self.current_time_lbl.SetLabel("00:00")
        self.total_time_lbl.SetLabel("00:00")
        self.chapter_choice.Clear()
        self.chapter_choice.Disable()
        self._chapter_pending_idx = None
        self._chapter_last_commit_idx = None
        self._chapter_last_commit_ts = 0.0
        self._refresh_chapter_controls_state()

        try:
            self.current_title = title or "Loading media..."
        except Exception:
            self.current_title = "Loading media..."
        try:
            self.title_lbl.SetLabel(self.current_title)
        except Exception:
            pass

        self._set_status("Connecting...")
        try:
            self._load_start_ts = float(time.monotonic())
        except Exception:
            pass

        try:
            t = threading.Thread(
                target=self._resolve_media_worker,
                args=(int(getattr(self, "_active_load_seq", 0)), str(url), bool(use_ytdlp), title, chapters),
                daemon=True,
            )
            t.start()
        except Exception:
            try:
                self._resolve_media_worker(
                    int(getattr(self, "_active_load_seq", 0)),
                    str(url),
                    bool(use_ytdlp),
                    title,
                    chapters,
                )
            except Exception:
                pass

    def toggle_play_pause(self) -> None:
        if self.is_audio_playing():
            self.pause()
        else:
            self.play()

    def update_chapters(self, chapters):
        self.current_chapters = chapters
        self.chapter_choice.Clear()
        self._chapter_pending_idx = None
        self._chapter_last_commit_idx = None
        self._chapter_last_commit_ts = 0.0
        if not chapters:
            self.chapter_choice.Disable()
            self._refresh_chapter_controls_state()
            return
            
        self.chapter_choice.Enable()
        for ch in chapters:
            start = ch.get("start", 0)
            mins = int(start // 60)
            secs = int(start % 60)
            title = ch.get("title", f"Chapter {start}")
            self.chapter_choice.Append(f"{title} - {mins:02d}:{secs:02d}", ch)
        self._refresh_chapter_controls_state()

    def on_play_pause(self, event):
        self.toggle_play_pause()

    def on_stop(self, event):
        self.stop()
            
    def _update_status_from_state(self, state, playing_now: bool) -> None:
        try:
            if not self.has_media_loaded():
                return
        except Exception:
            pass

        status = None
        try:
            if state in (vlc.State.Opening, vlc.State.Buffering):
                status = "Buffering..."
            elif playing_now:
                status = "Playing"
            elif state == vlc.State.Paused:
                status = "Paused"
            elif state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                status = "Stopped"
        except Exception:
            status = None

        if status is not None:
            self._set_status(status)

    def on_timer(self, event):
        if self.is_casting:
            try:
                now = time.time()
                if now - float(getattr(self, '_cast_poll_ts', 0.0)) >= 1.0:
                    self._cast_poll_ts = now
                    pos_sec = self.casting_manager.get_position()
                    if pos_sec is not None:
                        val = int(float(pos_sec) * 1000.0)
                        # Only update if > 0 to avoid overwriting valid progress with 0 during glitches
                        if val > 0:
                            self._cast_last_pos_ms = val
            except Exception:
                pass
            try:
                self._persist_playback_position(force=False)
            except Exception:
                pass
            return

        try:
            length = int(self.player.get_length() or 0)
            if length > 0 and length != int(getattr(self, 'duration', 0) or 0):
                self.duration = int(length)
                try:
                    self.total_time_lbl.SetLabel(self._format_time(int(length)))
                except Exception:
                    pass
        except Exception:
            pass

        playing_now = False
        try:
            playing_now = bool(self.player.is_playing())
        except Exception:
            playing_now = False
        try:
            state = None
            try:
                state = self.player.get_state()
            except Exception:
                state = None
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                if bool(getattr(self, "is_playing", False)):
                    self.is_playing = False
                    self._set_play_button_label(False)
            elif playing_now and not bool(getattr(self, "is_playing", False)):
                self.is_playing = True
                self._set_play_button_label(True)
        except Exception:
            pass

        try:
            self._update_status_from_state(state, playing_now)
        except Exception:
            pass

        try:
            self._maybe_start_pending_silence_scan(bool(playing_now))
        except Exception:
            pass

        now_mono = time.monotonic()
        try:
            self._pos_last_timer_ts = float(now_mono)
        except Exception:
            pass

        vlc_cur = 0
        try:
            vlc_cur = int(self.player.get_time() or 0)
        except Exception:
            vlc_cur = 0
        if vlc_cur < 0:
            vlc_cur = 0
        try:
            self._maybe_recover_stalled_direct_playback(state, bool(playing_now), int(vlc_cur))
        except Exception:
            pass
        try:
            self._maybe_recover_stalled_proxy_playback(state, bool(playing_now), int(vlc_cur))
        except Exception:
            pass

        try:
            ui_cur = int(getattr(self, "_pos_ms", 0) or 0)
        except Exception:
            ui_cur = 0

        try:
            recent_seek_target = getattr(self, "_seek_target_ms", None)
            recent_seek_ts = float(getattr(self, "_seek_target_ts", 0.0) or 0.0)
        except Exception:
            recent_seek_target = None
            recent_seek_ts = 0.0

        try:
            last_vlc = int(getattr(self, "_last_vlc_time_ms", 0) or 0)
        except Exception:
            last_vlc = 0
        try:
            allow_back = float(getattr(self, "_pos_allow_backwards_until_ts", 0.0) or 0.0)
        except Exception:
            allow_back = 0.0
        if playing_now and last_vlc > 0 and vlc_cur + 1200 < last_vlc and now_mono > allow_back:
            if recent_seek_target is None and getattr(self, "_pending_resume_seek_ms", None) is None:
                try:
                    last_warn = float(getattr(self, "_last_vlc_warn_ts", 0.0) or 0.0)
                except Exception:
                    last_warn = 0.0
                if (now_mono - last_warn) > 2.0:
                    skip = False
                    try:
                        skip = bool(self.config_manager.get("skip_silence", False))
                    except Exception:
                        skip = False
                    log.warning(
                        "VLC time jumped backward: prev=%sms cur=%sms delta=%sms skip_silence=%s",
                        int(last_vlc),
                        int(vlc_cur),
                        int(vlc_cur) - int(last_vlc),
                        skip,
                    )
                    self._last_vlc_warn_ts = float(now_mono)

        try:
            verify_until = float(getattr(self, "_silence_skip_verify_until_ts", 0.0) or 0.0)
        except Exception:
            verify_until = 0.0
        if verify_until:
            if now_mono > verify_until:
                self._silence_skip_verify_until_ts = 0.0
                self._silence_skip_verify_target_ms = None
                self._silence_skip_verify_source_ms = None
                self._silence_skip_verify_attempted = False
            else:
                try:
                    verify_target = getattr(self, "_silence_skip_verify_target_ms", None)
                    verify_source = getattr(self, "_silence_skip_verify_source_ms", None)
                except Exception:
                    verify_target = None
                    verify_source = None
                try:
                    verify_attempted = bool(getattr(self, "_silence_skip_verify_attempted", False))
                except Exception:
                    verify_attempted = False
                if verify_target is None or verify_source is None:
                    self._silence_skip_verify_until_ts = 0.0
                    self._silence_skip_verify_target_ms = None
                    self._silence_skip_verify_source_ms = None
                    self._silence_skip_verify_attempted = False
                else:
                    try:
                        url = getattr(self, "current_url", "") or ""
                    except Exception:
                        url = ""
                    is_remote = url.startswith("http") and not ("127.0.0.1" in url or "localhost" in url)
                    threshold = 1200 if is_remote else 700
                    target_gap = int(verify_target) - int(vlc_cur)
                    if target_gap <= int(threshold):
                        self._silence_skip_verify_until_ts = 0.0
                        self._silence_skip_verify_target_ms = None
                        self._silence_skip_verify_source_ms = None
                        self._silence_skip_verify_attempted = False
                    elif not verify_attempted:
                        try:
                            last_skip_ts = float(getattr(self, "_silence_skip_last_seek_ts", 0.0) or 0.0)
                        except Exception:
                            last_skip_ts = 0.0
                        min_wait = 0.5 if is_remote else 0.35
                        if (now_mono - float(last_skip_ts)) >= float(min_wait):
                            self._silence_skip_verify_attempted = True
                            try:
                                self._log_seek_event("silence_skip_verify", int(verify_target), int(vlc_cur))
                            except Exception:
                                pass
                            try:
                                self._apply_seek_time_ms(int(verify_target), force=True, reason="silence_skip_verify")
                            except Exception:
                                pass

        # Simplified logic: Trust our seek target for a few seconds after seeking.
        # Otherwise, trust VLC. This prevents "fighting" where VLC reports old time
        # during buffering and the UI jumps back and forth.
        if recent_seek_target is not None and (now_mono - float(recent_seek_ts)) < 4.0:
            try:
                tgt = int(recent_seek_target)
                # If VLC has actually jumped to the target (or close), we can sync early.
                if abs(int(vlc_cur) - int(tgt)) <= 2000:
                    ui_cur = int(vlc_cur)
                else:
                    ui_cur = int(tgt)
            except Exception:
                ui_cur = int(vlc_cur)
        else:
            ui_cur = int(vlc_cur)

        try:
            self._pos_ms = int(ui_cur)
            self._pos_ts = float(now_mono)
            self._last_vlc_time_ms = int(ui_cur)
        except Exception:
            pass

        try:
            if bool(getattr(self, "_silence_skip_reset_floor", False)):
                self._silence_skip_floor_ms = int(ui_cur)
                self._silence_skip_reset_floor = False
            else:
                try:
                    allow_back = float(getattr(self, "_pos_allow_backwards_until_ts", 0.0) or 0.0)
                except Exception:
                    allow_back = 0.0
                seek_floor = None
                try:
                    if recent_seek_target is not None and (now_mono - float(recent_seek_ts)) < 8.0:
                        seek_floor = int(recent_seek_target)
                except Exception:
                    seek_floor = None
                if now_mono < allow_back:
                    self._silence_skip_floor_ms = int(ui_cur)
                else:
                    floor = int(getattr(self, "_silence_skip_floor_ms", 0) or 0)
                    candidate = int(floor)
                    if seek_floor is not None and int(seek_floor) > int(candidate):
                        candidate = int(seek_floor)
                    if int(ui_cur) > int(candidate):
                        candidate = int(ui_cur)
                    if int(candidate) != int(floor):
                        self._silence_skip_floor_ms = int(candidate)
        except Exception:
            pass

        cur = int(vlc_cur)

        if getattr(self, '_pending_resume_seek_ms', None) is not None:
            try:
                restore_inflight = bool(getattr(self, "_resume_restore_inflight", False))
                restore_id = getattr(self, "_resume_restore_id", None)

                target_ms = int(self._pending_resume_seek_ms)
                if target_ms < 0: target_ms = 0
                if getattr(self, 'duration', 0) and int(self.duration) > 0 and target_ms > int(self.duration):
                    target_ms = int(self.duration)

                if restore_inflight:
                    # Restore from persisted position: request a single seek once VLC is ready, then wait.
                    if abs(int(cur) - int(target_ms)) <= 1500:
                        self._pending_resume_seek_ms = None
                        if restore_id:
                            try:
                                ok = playback_state.set_seek_supported(str(restore_id), True)
                                if ok is False:
                                    self._queue_resume_db_seek_supported(str(restore_id), True)
                            except Exception:
                                log.exception("Failed to update seek_supported=True for playback_state")
                        try:
                            self._resume_restore_inflight = False
                        except Exception:
                            pass
                    else:
                        state_i = None
                        try:
                            state_i = self.player.get_state()
                        except Exception as e:
                            log.debug("Failed to read VLC state: %s", e)
                            state_i = None

                        opening_states = (vlc.State.Opening, vlc.State.Buffering)
                        resume_max_attempts = 1
                        elapsed = 0.0
                        vlc_reports_unseekable = False
                        try:
                            vlc_reports_unseekable = hasattr(self.player, "is_seekable") and (self.player.is_seekable() is False)
                        except Exception as e:
                            log.debug("Failed to check VLC seekable flag: %s", e)
                            vlc_reports_unseekable = False

                        # If VLC reports the stream is not seekable, stop trying and remember it.
                        try:
                            already_tried = int(getattr(self, "_resume_restore_attempts", 0) or 0)
                            started_ts = float(getattr(self, "_resume_restore_started_ts", 0.0) or 0.0)
                            elapsed = float(now_mono) - float(started_ts) if started_ts else 0.0

                            player_stalled = state_i is not None and state_i not in opening_states

                            should_give_up = (
                                restore_id
                                and player_stalled
                                and already_tried >= resume_max_attempts
                                and elapsed >= 8.0
                                and vlc_reports_unseekable
                                and not self._current_input_looks_seekable()
                            )

                            if should_give_up:
                                ok = playback_state.set_seek_supported(str(restore_id), False)
                                if ok is False:
                                    self._queue_resume_db_seek_supported(str(restore_id), False)
                                self._pending_resume_seek_ms = None
                                self._resume_restore_inflight = False
                                restore_inflight = False
                        except Exception as e:
                            log.debug("Error evaluating seekability during resume restore: %s", e)

                        ready_for_seek = state_i is None or state_i not in opening_states

                        if restore_inflight:
                            # Don't spam play() while VLC is Opening/Buffering; load already starts playback.
                            if not ready_for_seek:
                                pass
                            else:
                                now_seek = time.monotonic()
                                try:
                                    last_attempt = float(getattr(self, "_resume_restore_last_attempt_ts", 0.0) or 0.0)
                                except Exception:
                                    last_attempt = 0.0
                                if (now_seek - last_attempt) >= 0.9:
                                    try:
                                        attempts = int(getattr(self, "_resume_restore_attempts", 0) or 0)
                                    except Exception:
                                        attempts = 0
                                    if attempts < resume_max_attempts:
                                        try:
                                            self.player.set_time(int(target_ms))
                                            try:
                                                ts = time.monotonic()
                                                self._seek_target_ms = int(target_ms)
                                                self._seek_target_ts = float(ts)
                                                self._pos_ms = int(target_ms)
                                                self._pos_ts = float(ts)
                                                self._last_vlc_time_ms = int(target_ms)
                                            except Exception:
                                                pass
                                        except Exception:
                                            pass
                                        try:
                                            self._resume_restore_attempts = int(attempts) + 1
                                            self._resume_restore_last_attempt_ts = float(now_seek)
                                        except Exception:
                                            pass
                                    else:
                                        # After the initial resume seek, avoid re-seeking (it can cause audio loops).
                                        # If VLC does not land close enough within a few seconds, give up for this
                                        # session without marking the source as unseekable.
                                        try:
                                            if (now_seek - float(last_attempt)) >= 8.0:
                                                self._pending_resume_seek_ms = None
                                                self._resume_restore_inflight = False
                                        except Exception:
                                            pass

                else:
                    # Legacy/in-flight resume path (cast handoff): keep it more aggressive.
                    if not playing_now:
                        try:
                            self.player.play()
                        except Exception:
                            pass
                        try:
                            playing_now = bool(self.player.is_playing())
                        except Exception:
                            playing_now = False

                    if abs(int(cur) - int(target_ms)) > 1500:
                        try:
                            try:
                                self._log_seek_event("resume_restore", int(target_ms), int(cur))
                            except Exception:
                                pass
                            self.player.set_time(int(target_ms))
                            try:
                                ts = time.monotonic()
                                self._seek_target_ms = int(target_ms)
                                self._seek_target_ts = float(ts)
                                self._pos_ms = int(target_ms)
                                self._pos_ts = float(ts)
                                self._last_vlc_time_ms = int(target_ms)
                            except Exception:
                                pass
                            try:
                                self._start_seek_guard(int(target_ms))
                            except Exception:
                                pass
                        except Exception:
                            pass
                    else:
                        self._pending_resume_seek_ms = None
                        if bool(getattr(self, '_pending_resume_paused', False)):
                            try:
                                self.player.set_pause(1)
                            except Exception:
                                try:
                                    self.player.pause()
                                except Exception:
                                    pass
                            self.is_playing = False

                    try:
                        self._pending_resume_seek_attempts = int(getattr(self, '_pending_resume_seek_attempts', 0) or 0) + 1
                    except Exception:
                        self._pending_resume_seek_attempts = 1
                    if (
                        self._pending_resume_seek_ms is not None
                        and int(getattr(self, '_pending_resume_seek_attempts', 0) or 0)
                        >= int(getattr(self, '_pending_resume_seek_max_attempts', 25) or 25)
                    ):
                        self._pending_resume_seek_ms = None
            except Exception:
                pass

        try:
            silence_pos = int(vlc_cur)
            if silence_pos < 0:
                silence_pos = 0
            self._maybe_skip_silence(int(silence_pos))
        except Exception:
            pass

        try:
            if not getattr(self, '_is_dragging_slider', False):
                self.current_time_lbl.SetLabel(self._format_time(int(ui_cur)))
        except Exception:
            pass

        try:
            if getattr(self, 'duration', 0) and int(self.duration) > 0:
                # Do NOT update the slider while the user is dragging it
                if not getattr(self, '_is_dragging_slider', False):
                    pos = int((float(ui_cur) / float(self.duration)) * 1000.0)
                    if pos < 0: pos = 0
                    if pos > 1000: pos = 1000
                    self.slider.SetValue(int(pos))
        except Exception:
            pass

        try:
            if self.current_chapters:
                cur_sec = float(ui_cur) / 1000.0
                idx = -1
                for i, ch in enumerate(self.current_chapters):
                    if cur_sec >= float(ch.get("start", 0) or 0):
                        idx = i
                    else:
                        break
                if idx != -1:
                    try:
                        if not self._is_focus_in_chapter_choice():
                            self.chapter_choice.SetSelection(int(idx))
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            self._persist_playback_position(force=False)
        except Exception:
            pass

    def on_slider_track(self, event):
        """Called repeatedly while dragging the slider."""
        self._is_dragging_slider = True
        try:
            val = self.slider.GetValue()
            if self.duration > 0:
                ms = int((val / 1000.0) * self.duration)
                self.current_time_lbl.SetLabel(self._format_time(ms))
        except Exception:
            pass
        # Do not call Skip to prevent interference, but usually safe to skip.
        event.Skip()

    def on_slider_release(self, event):
        """Called when slider is released (or clicked). Performs the seek."""
        self._is_dragging_slider = False
        self.on_seek(event) # Delegate to the actual seek logic

    def on_seek(self, event):
        """Handle final seek action."""
        if self.is_casting:
            try:
                if not self.duration or int(self.duration) <= 0:
                    return
                value = self.slider.GetValue()
                fraction = float(value) / 1000.0
                target_ms = int(fraction * int(self.duration))
                self._cast_last_pos_ms = int(target_ms)
                self.casting_manager.seek(float(target_ms) / 1000.0)
            except Exception:
                pass
            return

        if not self.duration or int(self.duration) <= 0:
            return
        value = self.slider.GetValue()
        fraction = float(value) / 1000.0
        target_ms = int(fraction * int(self.duration))
        try:
            self._note_user_seek()
        except Exception:
            log.exception("Error noting user seek on slider seek")
        # Force immediate seek on release
        self._apply_seek_time_ms(int(target_ms), force=True, reason="slider")
        try:
            self._schedule_resume_save_after_seek(delay_ms=400)
        except Exception:
            log.exception("Error scheduling resume save after slider seek")

    def on_rewind(self, event):
        if self.is_casting:
            try:
                cur_ms = int(getattr(self, '_cast_last_pos_ms', 0) or 0)
                if cur_ms <= 0:
                    pos_sec = self.casting_manager.get_position()
                    if pos_sec is not None:
                        cur_ms = int(float(pos_sec) * 1000.0)
                step = int(getattr(self, 'seek_back_ms', 10000) or 10000)
                target_ms = max(0, int(cur_ms) - int(step))
                self._cast_last_pos_ms = int(target_ms)
                self.casting_manager.seek(float(target_ms) / 1000.0)
            except Exception:
                pass
            return

        step = int(getattr(self, 'seek_back_ms', 10000) or 10000)
        self.seek_relative_ms(-int(step))

    def on_forward(self, event):
        if self.is_casting:
            try:
                cur_ms = int(getattr(self, '_cast_last_pos_ms', 0) or 0)
                if cur_ms <= 0:
                    pos_sec = self.casting_manager.get_position()
                    if pos_sec is not None:
                        cur_ms = int(float(pos_sec) * 1000.0)
                step = int(getattr(self, 'seek_forward_ms', 10000) or 10000)
                target_ms = int(cur_ms) + int(step)
                if getattr(self, 'duration', 0) and int(self.duration) > 0 and target_ms > int(self.duration):
                    target_ms = int(self.duration)
                self._cast_last_pos_ms = int(target_ms)
                self.casting_manager.seek(float(target_ms) / 1000.0)
            except Exception:
                pass
            return

        step = int(getattr(self, 'seek_forward_ms', 10000) or 10000)
        self.seek_relative_ms(int(step))

    def on_volume_slider(self, event):
        try:
            if getattr(self, "_volume_slider_updating", False):
                event.Skip()
                return
        except Exception:
            pass
        try:
            val = int(self.volume_slider.GetValue())
        except Exception:
            return
        self.set_volume_percent(val, persist=True)

    def on_speed_select(self, event):
        idx = self.speed_combo.GetSelection()
        if idx != wx.NOT_FOUND:
            speeds = utils.build_playback_speeds()
            if idx < len(speeds):
                speed = speeds[idx]
                self.set_playback_speed(speed)

    def set_playback_speed(self, speed):
        self.playback_speed = speed
        if not self.is_casting:
            try:
                self.player.set_rate(speed)
            except Exception:
                pass
        # Set combo selection
        speeds = utils.build_playback_speeds()
        try:
            idx = speeds.index(speed)
            self.speed_combo.SetSelection(idx)
        except ValueError:
            pass
        self.config_manager.set("playback_speed", speed)

    def on_chapter_select(self, event):
        # Do not seek on selection change so arrow-key browsing is safe.
        # Selection is committed on Enter (keyboard) or closeup (mouse/dropdown).
        try:
            self._chapter_pending_idx = int(self.chapter_choice.GetSelection())
        except Exception:
            self._chapter_pending_idx = None
        try:
            has_closeup = bool(getattr(self, "_chapter_closeup_supported", False))
        except Exception:
            has_closeup = False
        if not has_closeup:
            self._commit_chapter_selection()

    def on_chapter_closeup(self, event) -> None:
        try:
            self._commit_chapter_selection()
        except Exception:
            log.exception("Error committing chapter selection on closeup")
        try:
            event.Skip()
        except Exception:
            pass

    def _is_focus_in_chapter_choice(self) -> bool:
        try:
            chapter_choice = getattr(self, "chapter_choice", None)
            if chapter_choice is None:
                return False
        except Exception:
            return False

        focus = None
        try:
            focus = wx.Window.FindFocus()
        except Exception:
            focus = None

        try:
            while focus is not None:
                if focus == chapter_choice:
                    return True
                focus = focus.GetParent()
        except Exception:
            return False

        return False

    def _commit_chapter_selection(self) -> None:
        try:
            idx = int(self.chapter_choice.GetSelection())
        except Exception:
            idx = wx.NOT_FOUND

        if idx == wx.NOT_FOUND:
            return

        now_ts = time.monotonic()
        try:
            last_idx = getattr(self, "_chapter_last_commit_idx", None)
            last_ts = float(getattr(self, "_chapter_last_commit_ts", 0.0) or 0.0)
            if last_idx == int(idx) and (now_ts - last_ts) < 0.35:
                return
        except Exception:
            pass

        data = {}
        try:
            data = self.chapter_choice.GetClientData(int(idx)) or {}
        except Exception:
            data = {}

        try:
            start_sec = float(data.get("start", 0) or 0)
        except Exception:
            start_sec = 0.0

        if start_sec < 0:
            start_sec = 0.0

        if self.is_casting:
            # TODO: map chapters to casting seek when supported.
            return
        try:
            self._chapter_last_commit_idx = int(idx)
            self._chapter_last_commit_ts = float(now_ts)
        except Exception:
            pass

        try:
            self._note_user_seek()
        except Exception:
            log.exception("Error noting user seek on chapter selection")
        try:
            self._apply_seek_time_ms(int(start_sec * 1000.0), force=True, reason="chapter")
        except Exception:
            log.exception("Error applying seek on chapter selection")
        try:
            self._schedule_resume_save_after_seek(delay_ms=400)
        except Exception:
            log.exception("Error scheduling resume save after chapter selection")

    def _format_time(self, ms):
        seconds = ms // 1000
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins:02d}:{secs:02d}"

    # ---------------------------------------------------------------------
    # Media control helpers
    # ---------------------------------------------------------------------

    def has_media_loaded(self) -> bool:
        return bool(getattr(self, "current_url", None))

    def _set_play_button_label(self, playing: bool) -> None:
        try:
            if getattr(self, "play_btn", None):
                self.play_btn.SetLabel("Pause" if playing else "Play")
        except Exception:
            pass

    def _update_volume_ui(self, percent: int) -> None:
        try:
            self._volume_slider_updating = True
        except Exception:
            pass
        try:
            if getattr(self, "volume_slider", None):
                if int(self.volume_slider.GetValue()) != int(percent):
                    self.volume_slider.SetValue(int(percent))
            if getattr(self, "volume_value_lbl", None):
                self.volume_value_lbl.SetLabel(f"{int(percent)}%")
        except Exception:
            pass
        finally:
            try:
                self._volume_slider_updating = False
            except Exception:
                pass

    def is_current_media(self, article_id: object | None, media_url: str | None) -> bool:
        """Returns True if the given article_id/media_url matches what's currently loaded."""
        try:
            if not self.has_media_loaded():
                return False

            cur_id = getattr(self, "current_article_id", None)
            if cur_id is not None and article_id is not None and str(cur_id) == str(article_id):
                return True

            cur_url = getattr(self, "current_url", None)
            if cur_url and media_url and str(cur_url) == str(media_url):
                return True
        except Exception:
            log.exception("Error checking if media is current")
            return False

        return False

    def reload_current_media(self) -> bool:
        if not self.has_media_loaded():
            return False
        url = getattr(self, "current_url", None)
        if not url:
            return False
        try:
            use_ytdlp = bool(getattr(self, "_current_use_ytdlp", False))
        except Exception:
            use_ytdlp = False
        chapters = getattr(self, "_last_load_chapters", None)
        title = getattr(self, "_last_load_title", None) or getattr(self, "current_title", None)
        article_id = getattr(self, "current_article_id", None)
        try:
            self.load_media(url, use_ytdlp=use_ytdlp, chapters=chapters, title=title, article_id=article_id)
            return True
        except Exception:
            log.exception("Failed to reload current media")
            return False

    def resume_or_reload_current(self) -> None:
        if not self.has_media_loaded():
            return
        if self.is_casting:
            try:
                self.casting_manager.resume()
                self.is_playing = True
                self._set_play_button_label(True)
            except Exception:
                pass
            return
        state = None
        try:
            state = self.player.get_state()
        except Exception:
            state = None
        should_reload = False
        try:
            if state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
                should_reload = True
        except Exception:
            should_reload = False
        if should_reload:
            if self.reload_current_media():
                return
        self.play()

    def is_audio_playing(self) -> bool:
        """Return True only when audio is actively playing."""
        try:
            if bool(getattr(self, "is_casting", False)):
                return bool(getattr(self, "is_playing", False))
            try:
                return bool(self.player.is_playing())
            except Exception:
                return bool(getattr(self, "is_playing", False))
        except Exception:
            return False

    def set_volume_percent(self, percent: int, persist: bool = True) -> None:
        try:
            percent = int(percent)
        except Exception:
            percent = 100
        percent = max(0, min(100, percent))
        self.volume = percent

        if not self.is_casting:
            try:
                # Only call audio_set_volume if playing, OR if we want to risk unpausing.
                # User reported that changing volume unpauses playback.
                # So we guard it.
                should_set = True
                try:
                    if not self.player.is_playing():
                        should_set = False
                except Exception:
                    pass
                
                if should_set:
                    self.player.audio_set_volume(int(percent))
            except Exception:
                pass

        if self.is_casting:
            try:
                caster = getattr(self.casting_manager, "active_caster", None)
                if caster is not None and hasattr(caster, "set_volume"):
                    level = float(percent) / 100.0
                    self.casting_manager.dispatch(caster.set_volume(level))
            except Exception:
                pass
        if persist and self.config_manager:
            try:
                self.config_manager.set("volume", percent)
            except Exception:
                pass
        try:
            self._update_volume_ui(int(percent))
        except Exception:
            pass

    def _sync_volume_from_vlc(self) -> None:
        """Sync the volume slider with VLC's actual volume to prevent jumps on first adjustment."""
        if self.is_casting:
            return
        try:
            vlc_volume = self.player.audio_get_volume()
            if vlc_volume >= 0:  # -1 means error
                # Update our internal state and UI without persisting (already persisted)
                self.volume = int(vlc_volume)
                self._update_volume_ui(int(vlc_volume))
        except Exception:
            pass

    def adjust_volume(self, delta_percent: int) -> None:
        cur = int(getattr(self, "volume", 100))
        self.set_volume_percent(cur + int(delta_percent), persist=True)

    # ---------------------------------------------------------------------
    # Seek guard (local VLC)
    # ---------------------------------------------------------------------

    def _start_seek_guard(self, target_ms: int) -> None:
        if self.is_casting:
            return
        try:
            t = int(target_ms)
        except Exception:
            return
        if t < 0:
            t = 0
        self._seek_guard_target_ms = int(t)
        self._seek_guard_attempts_left = 10
        self._seek_guard_reapply_left = 3
        now = time.monotonic()
        self._seek_guard_last_cur_ms = None
        self._seek_guard_last_delta_ms = None
        self._seek_guard_last_progress_ts = float(now)
        try:
            if self._seek_guard_calllater is not None:
                try:
                    self._seek_guard_calllater.Stop()
                except Exception:
                    pass
                self._seek_guard_calllater = None
        except Exception:
            pass
        try:
            self._seek_guard_calllater = wx.CallLater(200, self._seek_guard_tick)
        except Exception:
            self._seek_guard_calllater = None

    def _seek_guard_tick(self) -> None:
        try:
            if self.is_casting:
                return
            left = int(getattr(self, "_seek_guard_attempts_left", 0) or 0)
            if left <= 0:
                return
            
            # 1. Check player state. If Opening (1) or Buffering (2), wait.
            # This prevents the Seek Guard from re-seeking while VLC is still filling its buffer.
            try:
                state = self.player.get_state()
                if state in (1, 2):
                    self._seek_guard_calllater = wx.CallLater(500, self._seek_guard_tick)
                    return
            except Exception:
                pass

            target = getattr(self, "_seek_guard_target_ms", None)
            if target is None:
                return
            target_i = int(target)

            cur = -1
            try:
                cur = int(self.player.get_time() or 0)
            except Exception:
                cur = -1
            
            # 2. Remote streams (YouTube etc) have very unreliable seeking.
            url = getattr(self, "current_url", "") or ""
            is_remote = url.startswith("http") and not ("127.0.0.1" in url or "localhost" in url)
            
            tolerance = 5000 if is_remote else 3000
            
            if cur >= 0 and abs(int(cur) - int(target_i)) <= tolerance:
                self._seek_guard_attempts_left = 0
                return

            # 3. Be extremely lenient with remote: stop trying much faster
            # to avoid the 'repeating' audio loop caused by constant re-seeks.
            if is_remote and left < 7:
                self._seek_guard_attempts_left = 0
                return

            now = time.monotonic()
            try:
                last_cur = getattr(self, "_seek_guard_last_cur_ms", None)
            except Exception:
                last_cur = None
            try:
                last_delta = getattr(self, "_seek_guard_last_delta_ms", None)
            except Exception:
                last_delta = None
            delta = None
            if cur >= 0:
                try:
                    delta = abs(int(cur) - int(target_i))
                except Exception:
                    delta = None

            if delta is not None:
                try:
                    if last_delta is None or int(delta) + 200 < int(last_delta):
                        self._seek_guard_last_progress_ts = float(now)
                except Exception:
                    pass

            try:
                self._seek_guard_last_cur_ms = int(cur)
                if delta is not None:
                    self._seek_guard_last_delta_ms = int(delta)
            except Exception:
                pass

            try:
                last_progress = float(getattr(self, "_seek_guard_last_progress_ts", 0.0) or 0.0)
            except Exception:
                last_progress = 0.0
            if delta is not None and (now - float(last_progress)) < 0.9:
                try:
                    self._seek_guard_calllater = wx.CallLater(500, self._seek_guard_tick)
                except Exception:
                    self._seek_guard_calllater = None
                return

            # Limited re-apply: be very conservative with re-seeking.
            try:
                retries = int(getattr(self, "_seek_guard_reapply_left", 0) or 0)
            except Exception:
                retries = 0
            
            if _should_reapply_seek(target_i, cur, tolerance, retries):
                try:
                    self._log_seek_event("seek_guard", int(target_i), int(cur))
                except Exception:
                    pass
                try:
                    self.player.set_time(int(target_i))
                except Exception:
                    pass
                retries -= 1
                self._seek_guard_reapply_left = retries

            try:
                self._pos_ms = int(target_i)
                self._pos_ts = time.monotonic()
            except Exception:
                pass

            left -= 1
            self._seek_guard_attempts_left = int(left)
            if left > 0:
                try:
                    # Increased check interval to 500ms to reduce overhead
                    self._seek_guard_calllater = wx.CallLater(500, self._seek_guard_tick)
                except Exception:
                    self._seek_guard_calllater = None
        except Exception:
            pass


    def _log_seek_event(self, reason: str, target_ms: int, cur_ms: int | None = None) -> None:
        try:
            now = time.monotonic()
        except Exception:
            now = 0.0
        try:
            last_ts = float(getattr(self, "_seek_log_last_ts", 0.0) or 0.0)
        except Exception:
            last_ts = 0.0
        if (now - last_ts) < 0.4:
            return

        try:
            cur_val = int(cur_ms) if cur_ms is not None else int(self.player.get_time() or 0)
        except Exception:
            cur_val = -1

        delta = None
        try:
            if cur_val >= 0:
                delta = int(target_ms) - int(cur_val)
        except Exception:
            delta = None

        must_log = reason in ("silence_skip", "silence_skip_verify", "seek_guard", "resume_restore")
        try:
            if delta is not None and (int(delta) < -1200 or abs(int(delta)) >= 6000):
                must_log = True
        except Exception:
            pass
        if not must_log:
            return

        try:
            self._seek_log_last_ts = float(now)
        except Exception:
            pass

        try:
            playing = bool(self.player.is_playing())
        except Exception:
            playing = bool(getattr(self, "is_playing", False))

        skip = False
        try:
            skip = bool(self.config_manager.get("skip_silence", False))
        except Exception:
            skip = False

        pending = False
        try:
            pending = getattr(self, "_pending_resume_seek_ms", None) is not None
        except Exception:
            pending = False

        log.info(
            "Seek event [%s]: cur=%s target=%s delta=%s playing=%s skip_silence=%s pending_resume=%s",
            reason,
            cur_val,
            int(target_ms),
            delta,
            playing,
            skip,
            pending,
        )

    def _apply_pending_seek(self) -> None:
        try:
            target = self._seek_apply_target_ms
            if target is None:
                return
            target_i = int(target)
        except Exception:
            return

        self._seek_apply_calllater = None
        now = time.monotonic()
        self._seek_apply_last_ts = now
        try:
            reason = getattr(self, "_seek_apply_reason", None) or "seek_apply"
        except Exception:
            reason = "seek_apply"
        reason_str = str(reason)
        try:
            self._log_seek_event(reason_str, int(target_i))
        except Exception:
            pass

        try:
            self._pos_ms = int(target_i)
            self._pos_ts = float(now)
            self._last_vlc_time_ms = int(target_i)
        except Exception:
            pass

        if reason_str.startswith("silence_skip"):
            try:
                self._seek_guard_target_ms = None
                self._seek_guard_attempts_left = 0
                self._seek_guard_reapply_left = 0
                self._stop_calllater("_seek_guard_calllater", "Failed to cancel seek guard for silence skip")
            except Exception:
                pass
        else:
            try:
                self._start_seek_guard(int(target_i))
            except Exception:
                pass

        try:
            self.player.set_time(target_i)
        except Exception:
            pass

        try:
            if self.duration and self.duration > 0:
                pos = max(0.0, min(1.0, float(target_i) / float(self.duration)))
                # Only update slider if we are not dragging it
                if not getattr(self, '_is_dragging_slider', False):
                    self.slider.SetValue(int(pos * 1000))
        except Exception:
            pass
        try:
            # Only update label if we are not dragging (dragging updates it separately)
            if not getattr(self, '_is_dragging_slider', False):
                self.current_time_lbl.SetLabel(self._format_time(target_i))
        except Exception:
            pass

    def _apply_debounced_seek(self) -> None:

        """Apply the most recent seek target once inputs have been idle."""

        try:

            self._seek_apply_calllater = None

        except Exception:

            pass

    

        now = time.monotonic()

        try:

            debounce = float(getattr(self, "_seek_apply_debounce_s", 0.18) or 0.18)

        except Exception:

            debounce = 0.18

        try:

            last_in = float(getattr(self, "_seek_input_ts", 0.0) or 0.0)

        except Exception:

            last_in = 0.0

    

        remain = float(debounce) - float(now - last_in)

        if remain > 0.02:

            try:

                self._seek_apply_calllater = wx.CallLater(max(1, int(remain * 1000)), self._apply_debounced_seek)

            except Exception:

                self._seek_apply_calllater = None

            return

    

        self._apply_pending_seek()

    

    def _apply_seek_time_ms(self, target_ms: int, force: bool = False, reason: str | None = None) -> None:
        log.debug("_apply_seek_time_ms target=%s force=%s", target_ms, force)
        if self.is_casting:
            return
        try:
            t = int(target_ms)
        except Exception:
            return
        if t < 0:
            t = 0

        self._seek_apply_target_ms = int(t)
        now = time.monotonic()
        try:
            self._seek_apply_reason = str(reason or "seek")
            self._seek_apply_reason_ts = float(now)
        except Exception:
            pass

        try:
            self._seek_input_ts = float(now)
        except Exception:
            pass

        try:
            self._seek_target_ms = int(t)
            self._seek_target_ts = float(now)
        except Exception:
            pass

        try:
            if int(t) + 1200 < int(getattr(self, "_pos_ms", 0) or 0):
                self._pos_allow_backwards_until_ts = float(now) + 3.0
        except Exception:
            pass

        # Cancel any pending debounced apply
        try:
            if self._seek_apply_calllater is not None:
                try:
                    self._seek_apply_calllater.Stop()
                except Exception:
                    pass
                self._seek_apply_calllater = None
        except Exception:
            pass

        if force:
            self._apply_pending_seek()
            return

        # If paused/stopped, apply immediately so it feels instant.
        playing_now = False
        try:
            playing_now = bool(self.player.is_playing())
        except Exception:
            playing_now = bool(getattr(self, "is_playing", False))

        if not playing_now:
            self._apply_pending_seek()
            return

        # While playing, limit how often we ask VLC to seek during a hold.
        try:
            last_apply = float(getattr(self, "_seek_apply_last_ts", 0.0) or 0.0)
        except Exception:
            last_apply = 0.0
        try:
            max_rate = float(getattr(self, "_seek_apply_max_rate_s", 0.35) or 0.35)
        except Exception:
            max_rate = 0.35

        if (now - last_apply) >= float(max_rate):
            self._apply_pending_seek()
            return

        # Otherwise debounce until inputs stop.
        try:
            debounce = float(getattr(self, "_seek_apply_debounce_s", 0.18) or 0.18)
        except Exception:
            debounce = 0.18
        try:
            self._seek_apply_calllater = wx.CallLater(max(1, int(float(debounce) * 1000)), self._apply_debounced_seek)
        except Exception:
            self._seek_apply_calllater = None


    def seek_relative_ms(self, delta_ms: int) -> None:
        if self.is_casting:
            return

        try:
            delta = int(delta_ms)
        except Exception:
            return

        try:
            self._note_user_seek()
        except Exception:
            log.exception("Error noting user seek in seek_relative_ms")

        now = time.monotonic()
        base = None
        try:
            if self._seek_target_ms is not None and (now - float(self._seek_target_ts)) < 1.0:
                base = int(self._seek_target_ms)
        except Exception:
            base = None

        if base is None:

            # Prefer our UI-tracked position (fast), but also consult VLC time so seeks

            # are correct even between slow timer ticks.

            try:

                ui_base = int(getattr(self, "_pos_ms", 0) or 0)

            except Exception:

                ui_base = 0

        

            vlc_base = None

            try:

                v = int(self.player.get_time() or 0)

                if v >= 0:

                    vlc_base = int(v)

            except Exception:

                vlc_base = None

        

            try:

                allow_back = float(getattr(self, "_pos_allow_backwards_until_ts", 0.0) or 0.0)

            except Exception:

                allow_back = 0.0

        

            if int(delta) < 0 or now < float(allow_back):

                # When rewinding (or shortly after), trust the UI target so repeated rewinds chain.

                base = int(ui_base)

            else:

                # Normal forward playback: VLC time may be more up-to-date than our 2s timer,

                # but VLC can briefly report stale/behind values after a seek. Use whichever is ahead.

                if vlc_base is not None:

                    base = int(max(int(ui_base), int(vlc_base)))

                    try:

                        self._pos_ms = int(base)

                        self._last_vlc_time_ms = int(base)

                    except Exception:

                        pass

                else:

                    base = int(ui_base)

        
        target = int(base) + delta

        try:
            if self.duration and self.duration > 0:
                target = max(0, min(int(target), int(self.duration)))
            else:
                target = max(0, int(target))
        except Exception:
            try:
                target = max(0, int(target))
            except Exception:
                return

        try:
            if int(delta) < 0:
                self._pos_allow_backwards_until_ts = float(now) + 3.0
        except Exception:
            pass

        self._seek_target_ms = int(target)
        self._seek_target_ts = float(now)
        try:
            self._pos_ms = int(target)
            self._pos_ts = float(now)
            self._last_vlc_time_ms = int(target)
        except Exception:
            pass

        try:
            if self.duration and self.duration > 0:
                pos = max(0.0, min(1.0, float(target) / float(self.duration)))
                self.slider.SetValue(int(pos * 1000))
            self.current_time_lbl.SetLabel(self._format_time(int(target)))
        except Exception:
            pass

        self._apply_seek_time_ms(int(target), force=False, reason="seek_relative")
        try:
            self._schedule_resume_save_after_seek()
        except Exception:
            log.exception("Error scheduling resume save in seek_relative_ms")

    def play(self) -> None:
        log.debug("play called")
        if not self.has_media_loaded():
            return
        if not self.is_casting and not self._ensure_vlc_ready():
            return
        if self.is_casting:
            try:
                self.casting_manager.resume()
            except Exception:
                pass
            self.is_playing = True
            self._set_play_button_label(True)
            self._set_status("Playing")
        else:
            try:
                try:
                    if getattr(self, "_stopped_needs_resume", False):
                        resume_id = self._get_resume_id()
                        if resume_id:
                            self._maybe_restore_playback_position(str(resume_id), getattr(self, "current_title", None))
                except Exception:
                    log.exception("Error handling resume on play")
                finally:
                    self._stopped_needs_resume = False

                try:
                    self.player.set_pause(0)
                except Exception:
                    pass
                self.player.play()
                self.is_playing = True
                try:
                    self.player.audio_set_volume(int(getattr(self, "volume", 100)))
                except Exception:
                    pass
                
                # Sync the volume slider with VLC's actual volume to prevent jumps on first adjustment
                try:
                    wx.CallLater(500, self._sync_volume_from_vlc)
                except Exception:
                    pass
                
                self._set_play_button_label(True)
                self._set_status("Playing")
                if not self.timer.IsRunning():
                    interval = 500
                    try:
                        if getattr(self, "_pending_resume_seek_ms", None) is not None or bool(self.config_manager.get("skip_silence", False)):
                            interval = 250
                    except Exception:
                        interval = 500
                    self.timer.Start(int(interval))
            except Exception:
                pass

    def pause(self) -> None:
        log.debug("pause called")
        if not self.has_media_loaded():
            return
        if not self.is_casting and not self._ensure_vlc_ready():
            return
        try:
            self._persist_playback_position(force=True)
        except Exception:
            log.exception("Failed to persist playback position on pause")
        if self.is_casting:
            try:
                self.casting_manager.pause()
                self.is_playing = False
                self._set_play_button_label(False)
                self._set_status("Paused")
            except Exception:
                pass
        else:
            try:
                try:
                    self.player.set_pause(1)
                except Exception:
                    # Fallback to toggle pause
                    try:
                        self.player.pause()
                    except OSError:
                        log.warning("VLC pause failed; reinitializing player")
                        self._init_vlc()
                        return
                self.is_playing = False
                self._set_play_button_label(False)
                self._set_status("Paused")
            except Exception:
                log.exception("Failed to pause player")

    def stop(self) -> None:
        if not self.is_casting and not self._ensure_vlc_ready():
            return
        try:
            self._persist_playback_position(force=True)
        except Exception:
            log.exception("Failed to persist playback position on stop")
        try:
            self._cancel_scheduled_resume_save()
        except Exception:
            log.exception("Error canceling scheduled resume save on stop")
        self._stop_calllater("_seek_apply_calllater", "Error handling seek apply calllater on stop")
        if self.is_casting:
            try:
                self.casting_manager.stop_playback()
            except Exception:
                pass
        else:
            try:
                self.player.stop()
            except Exception:
                pass

        try:
            self.timer.Stop()
        except Exception:
            pass

        self._cancel_silence_scan()
        self.is_playing = False
        self._set_play_button_label(False)
        self._set_status("Stopped")

        try:
            self.slider.SetValue(0)
            self.current_time_lbl.SetLabel("00:00")
            self.total_time_lbl.SetLabel(self._format_time(self.duration) if self.duration else "00:00")
        except Exception:
            pass
        self._stopped_needs_resume = True

    def on_char_hook(self, event: wx.KeyEvent) -> None:
        try:
            key = int(event.GetKeyCode())
        except Exception:
            key = None

        if key in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER):
            try:
                if self._is_focus_in_chapter_choice():
                    self._commit_chapter_selection()
                    return
            except Exception:
                pass

        if event.ControlDown() and event.ShiftDown() and not event.AltDown() and not event.MetaDown():
            if key == wx.WXK_LEFT:
                try:
                    self.prev_chapter()
                    return
                except Exception:
                    pass
            elif key == wx.WXK_RIGHT:
                try:
                    self.next_chapter()
                    return
                except Exception:
                    pass

        if event.ControlDown() and not event.ShiftDown() and not event.AltDown() and not event.MetaDown():
            actions = {
                wx.WXK_UP: lambda: self.adjust_volume(int(getattr(self, "volume_step", 5))),
                wx.WXK_DOWN: lambda: self.adjust_volume(-int(getattr(self, "volume_step", 5))),
                wx.WXK_LEFT: lambda: self.seek_relative_ms(-int(getattr(self, "seek_back_ms", 10000))),
                wx.WXK_RIGHT: lambda: self.seek_relative_ms(int(getattr(self, "seek_forward_ms", 10000))),
            }

            try:
                if key in (wx.WXK_LEFT, wx.WXK_RIGHT):
                    if not self.has_media_loaded():
                        event.Skip()
                        return
            except Exception:
                pass

            handled = False
            try:
                if getattr(self, "_media_hotkeys", None):
                    handled = bool(self._media_hotkeys.handle_ctrl_key(event, actions))
            except Exception:
                handled = False
            if handled:
                return

            action = actions.get(key)
            if action is not None:
                try:
                    action()
                    return
                except Exception:
                    pass
        event.Skip()

    def on_close(self, event):
        try:
            self.shutdown()
        except Exception:
            log.exception("Error during player shutdown")
        try:
            self._set_status("Stopped")
        except Exception:
            pass
        try:
            self.Hide()
        except Exception:
            pass

    def shutdown(self) -> None:
        """Stop playback/timers so the app can exit cleanly."""
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True

        try:
            self._persist_playback_position(force=True)
        except Exception:
            log.exception("Failed to persist playback position during shutdown")

        try:
            self._stop_calllater("_resume_pending_db_flush_calllater", "Error canceling resume DB flush during shutdown")
            self._flush_pending_resume_db_writes()
        except Exception:
            log.exception("Error flushing pending resume DB writes during shutdown")

        try:
            self._cancel_scheduled_resume_save()
        except Exception:
            log.exception("Error canceling scheduled resume save during shutdown")

        self._stop_calllater("_seek_apply_calllater", "Error handling seek apply calllater during shutdown")
        self._stop_calllater("_seek_guard_calllater", "Error handling seek guard calllater during shutdown")

        try:
            self._cancel_silence_scan()
        except Exception:
            log.exception("Error canceling silence scan during shutdown")

        try:
            self.timer.Stop()
        except Exception:
            log.exception("Error stopping timer during shutdown")

        if bool(getattr(self, "is_casting", False)):
            try:
                self.casting_manager.stop_playback()
            except Exception:
                log.exception("Error stopping casting playback during shutdown")
            try:
                self.casting_manager.disconnect()
            except Exception:
                log.exception("Error disconnecting from cast device during shutdown")

        if getattr(self, "player", None) is not None:
            try:
                self.player.stop()
            except Exception:
                log.exception("Error stopping VLC player during shutdown")
            try:
                self.player.release()
            except Exception:
                log.exception("Error releasing VLC player during shutdown")
            try:
                self.player = None
            except Exception:
                pass

        if getattr(self, "instance", None) is not None:
            try:
                self.instance.release()
            except Exception:
                log.exception("Error releasing VLC instance during shutdown")
            try:
                self.instance = None
            except Exception:
                pass
        try:
            self.event_manager = None
            self.initialized = False
        except Exception:
            pass

        try:
            if getattr(self, "casting_manager", None) is not None:
                self.casting_manager.stop()
        except Exception:
            log.exception("Error stopping casting manager during shutdown")

        try:
            if getattr(self, "_media_hotkeys", None):
                self._media_hotkeys.stop()
        except Exception:
            log.exception("Error stopping media hotkeys during shutdown")
