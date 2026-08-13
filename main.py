# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import warnings
# Suppress pkg_resources deprecation noise from webrtcvad immediately
warnings.filterwarnings("ignore", category=UserWarning, message=r"pkg_resources is deprecated as an API.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

from core.runtime_env import configure_runtime_environment

configure_runtime_environment()

import sys
import multiprocessing
import logging
import threading
import os

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy third-party loggers
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
logging.getLogger("readability").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)


# Elevated one-shot helper: derive Chromium v20 cookie master keys as SYSTEM.
# Runs in a separate elevated process (invoked via ShellExecute "runas") and
# must exit before any GUI work begins. See core/chromium_cookies.py.
if "--blindrss-chromium-key-helper" in sys.argv[1:]:
    from core.chromium_cookies import run_key_helper_cli

    sys.exit(run_key_helper_cli(sys.argv[1:]))

if "--blindrss-chromium-vss-copy" in sys.argv[1:]:
    from core.chromium_cookies import run_vss_copy_cli

    sys.exit(run_vss_copy_cli(sys.argv[1:]))

if "--blindrss-elevated-helper" in sys.argv[1:]:
    from core.chromium_cookies import run_elevated_helper_cli

    sys.exit(run_elevated_helper_cli(sys.argv[1:]))


def _configure_file_logging(config_manager):
    """Attach a persistent debug log after config has resolved the data directory."""
    try:
        root = logging.getLogger()
        debug_mode = bool(config_manager.get("debug_mode", False))

        for handler in list(root.handlers):
            if getattr(handler, "_blindrss_file_handler", False):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        if not debug_mode:
            root.setLevel(logging.INFO)
            logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
            logging.getLogger("readability").setLevel(logging.CRITICAL)
            return None

        from logging.handlers import RotatingFileHandler
        from core.config import get_data_dir

        log_dir = get_data_dir()
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "blindrss.log")

        root.setLevel(logging.DEBUG)
        for handler in root.handlers:
            handler.setLevel(logging.DEBUG)

        handler = RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler._blindrss_file_handler = True
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
        root.addHandler(handler)

        # In debug mode, the file should capture all app/third-party logging that reaches Python logging.
        logging.getLogger("trafilatura").setLevel(logging.NOTSET)
        logging.getLogger("readability").setLevel(logging.NOTSET)
        log.debug("Debug logging to %s", log_path)
        return log_path
    except Exception as e:
        log.error("Failed to configure file logging: %s", e)
        return None

def _rebind_logging_streams():
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setStream(sys.stderr)

def _enable_debug_console(config_manager):
    if not sys.platform.startswith("win"):
        return
    if not bool(config_manager.get("debug_mode", False)):
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        if kernel32.GetConsoleWindow():
            return
        if not kernel32.AllocConsole():
            return
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        _rebind_logging_streams()
    except Exception as e:
        log.error(f"Failed to open debug console: {e}")

# Essential imports
from core.dependency_check import check_and_install_dependencies, set_user_tool_paths

# A runtime-updated yt_dlp package (downloaded in the background by
# ensure_ytdlp_module_updated) must shadow the frozen-in bundled copy BEFORE
# anything imports yt_dlp; every app import of it is lazy, so doing it here at
# module import time is early enough. No-op for source checkouts (pip-managed).
try:
    from core.dependency_check import prefer_updated_ytdlp_module
    prefer_updated_ytdlp_module()
except Exception:
    pass

import wx
from core.config import ConfigManager
from core.factory import get_provider
from core.i18n import _
from core import updater as app_updater
from core import windows_integration
from gui.mainframe import MainFrame
from gui import hotkeys as _hotkeys
from core.stream_proxy import get_proxy
from core.range_cache_proxy import get_range_cache_proxy
from core import vlc_instance

def _build_media_actions(pw):
    """Seek/volume callbacks keyed by arrow keycode for HoldRepeatHotkeys."""
    return {
        wx.WXK_UP: lambda: pw.adjust_volume(int(getattr(pw, "volume_step", 5))),
        wx.WXK_DOWN: lambda: pw.adjust_volume(-int(getattr(pw, "volume_step", 5))),
        wx.WXK_LEFT: lambda: pw.seek_relative_ms(-int(getattr(pw, "seek_back_ms", 10000))),
        wx.WXK_RIGHT: lambda: pw.seek_relative_ms(int(getattr(pw, "seek_forward_ms", 10000))),
    }


class _ListItemErrorLogFilter(wx.Log):
    """Drop only the benign "list control item" wxLogError; forward everything else.

    wx.ListCtrl.GetItem/GetItemText/SetItem on an out-of-range row do not raise a
    Python exception — they call wxLogError("Couldn't retrieve information about
    list control item N."), which the default wx log target flushes as a modal
    "BlindRSS Error" dialog. try/except around the call cannot suppress it. Those
    reads are always momentary and harmless here (e.g. a timer callback touching a
    row while the article list is mid-rebuild after expanding/selecting a category),
    so this filter swallows that one message and passes all other wx log records
    through to the previously active target unchanged.
    """

    _NEEDLE = "information about list control item"

    def __init__(self, previous):
        super().__init__()
        self._previous = previous

    def DoLogRecord(self, level, msg, info):
        try:
            if self._NEEDLE in (msg or ""):
                return
        except Exception:
            pass
        prev = self._previous
        if prev is not None:
            try:
                prev.LogRecord(level, msg, info)
            except Exception:
                pass


def _install_wx_log_filter():
    """Route wx logging through _ListItemErrorLogFilter (see its docstring)."""
    try:
        previous = wx.Log.GetActiveTarget()
        if previous is None:
            # No default target yet: installing a forwarder with nowhere to
            # forward would swallow every wx error. Leave wx's default in place.
            return
        wx.Log.SetActiveTarget(_ListItemErrorLogFilter(previous))
    except Exception as e:
        log.debug(f"Could not install wx log filter: {e}")


class GlobalMediaKeyFilter(wx.EventFilter):
    """Capture media shortcuts globally so they work in dialogs too."""

    def __init__(self, frame: MainFrame):
        super().__init__()
        self.frame = frame

    def FilterEvent(self, event):
        try:
            # Check if the frame is still alive (C++ object valid)
            if not self.frame:
                return wx.EventFilter.Event_Skip

            if not isinstance(event, wx.KeyEvent):
                return wx.EventFilter.Event_Skip

            # Only react to key-down/char events. Handling KEY_UP can cause double-seeks.
            try:
                et = int(event.GetEventType())
            except Exception:
                et = -1
            if et not in (getattr(wx, 'wxEVT_KEY_DOWN', -1), getattr(wx, 'wxEVT_CHAR_HOOK', -1), getattr(wx, 'wxEVT_CHAR', -1)):
                return wx.EventFilter.Event_Skip

            key = int(event.GetKeyCode())

            # Ctrl+P: play/pause via the shortcut registry (player.play_pause).
            # This used to hard-toggle the player window, which shadowed the
            # registry's Ctrl+P play/pause binding — pressing Ctrl+P during
            # playback showed/hid the player instead of pausing. Delegating to
            # dispatch_shortcut lets the user's binding win, applies the
            # text-input guard (so it never hijacks Ctrl+P while typing), and
            # keeps it working while a dialog is focused. Show/hide the player
            # is Ctrl+Shift+P (player.show_hide).
            if (
                event.ControlDown()
                and not event.ShiftDown()
                and not event.AltDown()
                and not event.MetaDown()
                and key in (ord('P'), ord('p'))
            ):
                try:
                    focus = wx.Window.FindFocus()
                    if self.frame.dispatch_shortcut(event, focus=focus, apply_text_guard=True):
                        return wx.EventFilter.Event_Processed
                except Exception as e:
                    log.debug(f"Error dispatching Ctrl+P play/pause: {e}")
                return wx.EventFilter.Event_Skip

            # Seek/volume arrows: Ctrl+Arrow everywhere, plus Alt(Option)+Arrow
            # on macOS where Ctrl+Left/Right are taken by Mission Control.
            action_name = _hotkeys.resolve_media_action(
                sys.platform,
                ctrl=event.ControlDown(),
                alt=event.AltDown(),
                shift=event.ShiftDown(),
                meta=event.MetaDown(),
                keycode=key,
            )
            if action_name is not None:
                pw = getattr(self.frame, "player_window", None)
                if pw:
                    # Mirror the Ctrl+Arrow gating: only act while audio is playing,
                    # so Alt+Arrow stays free for list/reader navigation otherwise.
                    hk = getattr(self.frame, "_media_hotkeys", None)
                    if hk is not None:
                        playing = False
                        try:
                            playing = bool(getattr(pw, "is_audio_playing", lambda: False)())
                        except Exception:
                            playing = False
                        if playing:
                            actions = _build_media_actions(pw)
                            if hk.handle_ctrl_key(event, actions):
                                return wx.EventFilter.Event_Processed
        except Exception as e:
            # Suppress dead object errors during shutdown
            if "PyDeadObjectError" not in str(e):
                log.debug(f"Error in GlobalMediaKeyFilter: {e}")
        return wx.EventFilter.Event_Skip

class RSSApp(wx.App):
    def OnInit(self):
        self.config_manager = ConfigManager()
        # Install UI translations before any UI message is shown, including the
        # single-instance check below (issues #44, #61). "auto" follows the OS
        # locale; English is the fallback.
        try:
            from core import i18n
            i18n.setup(self.config_manager.get("language", "auto"))
        except Exception:
            log.debug("Failed to initialize translations", exc_info=True)

        _install_wx_log_filter()

        self.instance_checker = wx.SingleInstanceChecker("BlindRSS-Instance-Lock")
        if self.instance_checker.IsAnotherRunning():
            wx.MessageBox(_("BlindRSS is already running."), "BlindRSS", wx.ICON_ERROR)
            return False

        try:
            set_user_tool_paths({
                "ffmpeg": self.config_manager.get("custom_ffmpeg_path", ""),
                "ffprobe": self.config_manager.get("custom_ffprobe_path", ""),
                "yt-dlp": self.config_manager.get("custom_ytdlp_path", ""),
            })
        except Exception:
            pass
        try:
            from core import captcha_solver

            captcha_solver.configure_from_config(self.config_manager.get)
        except Exception:
            pass
        _enable_debug_console(self.config_manager)
        self.log_path = _configure_file_logging(self.config_manager)
        if sys.platform.startswith("win"):
            try:
                ok, msg = windows_integration.ensure_notification_prerequisites(
                    ensure_start_menu_shortcut=True
                )
                if not ok:
                    log.warning("Windows notification prerequisites are incomplete: %s", msg)
            except Exception:
                log.exception("Failed to enforce Windows notification prerequisites")
        try:
            app_updater.cleanup_update_artifacts()
        except Exception as e:
            log.debug(f"Update cleanup failed: {e}")

        self.provider = get_provider(self.config_manager)
        
        self.frame = MainFrame(self.provider, self.config_manager)
        self.frame.Show(not bool(self.config_manager.get("start_in_system_tray", False)))

        # Warm the shared libVLC instance on a background thread shortly after
        # startup so the first playback doesn't wait on the plugin scan.
        wx.CallLater(1200, lambda: vlc_instance.warm_async(self.config_manager))

        # Run dependency check after the UI is visible to reduce startup work.
        wx.CallLater(2000, lambda: threading.Thread(target=check_and_install_dependencies, daemon=True).start())

        # Watch the Downloads folder for a freshly exported YouTube cookies.txt
        # and auto-import it (Chromium App-Bound Encryption blocks reading those
        # cookies directly, so the user exports once and we pick it up hands-free).
        self._cookie_watcher = None
        try:
            from core.cookies_import import CookieImportWatcher
            from core.config import get_data_dir

            self._cookie_watcher = CookieImportWatcher(
                self.config_manager,
                get_data_dir(),
                on_import=self._on_cookies_auto_imported,
                on_site_import=self._on_site_cookies_auto_imported,
                on_browser_import=self._on_browser_cookies_auto_imported,
            )
            self._cookie_watcher.start()
        except Exception as e:
            log.debug(f"Cookie import watcher not started: {e}")

        # Install a global filter so media shortcuts work everywhere (including modal dialogs)
        try:
            # Keep a reference so it is not garbage-collected.
            self._media_filter = GlobalMediaKeyFilter(self.frame)
            wx.EvtHandler.AddFilter(self._media_filter)
        except Exception as e:
            log.error(f"Failed to install global media filter: {e}")
        return True

    def _on_cookies_auto_imported(self, dest_path):
        """Notify the user (on the UI thread) when cookies were auto-imported."""
        def _notify():
            try:
                frame = getattr(self, "frame", None)
                msg = "Imported YouTube login cookies from your browser export. They will be used for restricted videos."
                if frame is not None and hasattr(frame, "_show_windows_notification"):
                    frame._show_windows_notification("BlindRSS cookies updated", msg)
                else:
                    log.info(msg)
            except Exception as e:
                log.debug(f"Cookie auto-import notification failed: {e}")

        try:
            wx.CallAfter(_notify)
        except Exception:
            log.info("Auto-imported YouTube cookies to %s", dest_path)

    def _on_site_cookies_auto_imported(self, src_path):
        """Notify when a fresh Downloads cookies.txt was merged into the site jar."""
        def _notify():
            try:
                frame = getattr(self, "frame", None)
                name = os.path.basename(str(src_path or ""))
                msg = (
                    f"Imported website cookies from {name}. "
                    "Sites behind a browser verification page should now load."
                )
                if frame is not None and hasattr(frame, "_show_windows_notification"):
                    frame._show_windows_notification("BlindRSS cookies updated", msg)
                else:
                    log.info(msg)
            except Exception as e:
                log.debug(f"Site cookie auto-import notification failed: {e}")

        try:
            wx.CallAfter(_notify)
        except Exception:
            log.info("Auto-imported site cookies from %s", src_path)

    def _on_browser_cookies_auto_imported(self, stats):
        """Notify when session cookies were harvested from installed browsers."""
        def _notify():
            try:
                frame = getattr(self, "frame", None)
                count = int((stats or {}).get("cookies", 0) or 0)
                youtube = int((stats or {}).get("youtube", 0) or 0)
                msg = f"Read {count} cookie(s) from your installed browsers."
                if youtube:
                    msg += " YouTube login is now available."
                if frame is not None and hasattr(frame, "_show_windows_notification"):
                    frame._show_windows_notification("BlindRSS cookies updated", msg)
                else:
                    log.info(msg)
            except Exception as e:
                log.debug(f"Browser cookie auto-import notification failed: {e}")

        try:
            wx.CallAfter(_notify)
        except Exception:
            log.info("Auto-imported browser cookies: %s", stats)

    def OnExit(self):
        log.info("Shutting down proxies...")
        try:
            watcher = getattr(self, "_cookie_watcher", None)
            if watcher is not None:
                watcher.stop()
        except Exception as e:
            log.debug(f"Error stopping cookie watcher: {e}")
        try:
            get_proxy().stop()
        except Exception as e:
            log.error(f"Error stopping StreamProxy: {e}")
        
        try:
            get_range_cache_proxy().stop()
        except Exception as e:
            log.error(f"Error stopping RangeCacheProxy: {e}")

        try:
            vlc_instance.release_shared()
        except Exception as e:
            log.error(f"Error releasing shared VLC instance: {e}")

        # The gated-page fallback keeps a headless Chromium warm between fetches;
        # without this it would outlive the app as an orphan process.
        try:
            from core import browser_feed
            browser_feed.shutdown()
        except Exception as e:
            log.error(f"Error closing the automated browser session: {e}")
            
        # Release the lock implicitly by object destruction, but explicit delete is good practice
        try:
            del self.instance_checker
        except Exception:
            pass
        return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app = RSSApp()
    app.MainLoop()
