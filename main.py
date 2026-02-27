import warnings
# Suppress pkg_resources deprecation noise from webrtcvad immediately
warnings.filterwarnings("ignore", category=UserWarning, message=r"pkg_resources is deprecated as an API.*")
warnings.filterwarnings("ignore", category=UserWarning, module="pkg_resources")

import sys
import multiprocessing
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# Silence noisy third-party loggers
logging.getLogger("trafilatura").setLevel(logging.CRITICAL)
logging.getLogger("readability").setLevel(logging.CRITICAL)
log = logging.getLogger(__name__)

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
from core.dependency_check import check_and_install_dependencies
import wx
from core.config import ConfigManager
from core.factory import get_provider
from core import updater as app_updater
from core import windows_integration
from gui.mainframe import MainFrame
from core.stream_proxy import get_proxy
from core.range_cache_proxy import get_range_cache_proxy

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

            if event.ControlDown() and not event.ShiftDown() and not event.AltDown() and not event.MetaDown():
                key = int(event.GetKeyCode())

                # Ctrl+P: toggle player window
                if key in (ord('P'), ord('p')):
                    try:
                        self.frame.toggle_player_visibility()
                    except Exception as e:
                        log.debug(f"Error toggling player visibility: {e}")
                    return wx.EventFilter.Event_Processed

                pw = getattr(self.frame, "player_window", None)
                if pw:
                    # Use the same hold-to-repeat gate everywhere to avoid multi-seek bursts.
                    hk = getattr(self.frame, "_media_hotkeys", None)
                    if hk is not None:
                        playing = False
                        try:
                            playing = bool(getattr(pw, "is_audio_playing", lambda: False)())
                        except Exception:
                            playing = False
                        if playing:
                            actions = {
                                wx.WXK_UP: lambda: pw.adjust_volume(int(getattr(pw, "volume_step", 5))),
                                wx.WXK_DOWN: lambda: pw.adjust_volume(-int(getattr(pw, "volume_step", 5))),
                                wx.WXK_LEFT: lambda: pw.seek_relative_ms(-int(getattr(pw, "seek_back_ms", 10000))),
                                wx.WXK_RIGHT: lambda: pw.seek_relative_ms(int(getattr(pw, "seek_forward_ms", 10000))),
                            }
                            if hk.handle_ctrl_key(event, actions):
                                return wx.EventFilter.Event_Processed
        except Exception as e:
            # Suppress dead object errors during shutdown
            if "PyDeadObjectError" not in str(e):
                log.debug(f"Error in GlobalMediaKeyFilter: {e}")
        return wx.EventFilter.Event_Skip

class RSSApp(wx.App):
    def OnInit(self):
        self.instance_checker = wx.SingleInstanceChecker("BlindRSS-Instance-Lock")
        if self.instance_checker.IsAnotherRunning():
            wx.MessageBox("BlindRSS is already running.", "BlindRSS", wx.ICON_ERROR)
            return False

        self.config_manager = ConfigManager()
        _enable_debug_console(self.config_manager)
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
        self.frame.Show()

        # Run dependency check after the UI is visible to reduce startup work.
        wx.CallLater(2000, lambda: threading.Thread(target=check_and_install_dependencies, daemon=True).start())

        # Install a global filter so media shortcuts work everywhere (including modal dialogs)
        try:
            # Keep a reference so it is not garbage-collected.
            self._media_filter = GlobalMediaKeyFilter(self.frame)
            wx.EvtHandler.AddFilter(self._media_filter)
        except Exception as e:
            log.error(f"Failed to install global media filter: {e}")
        return True

    def OnExit(self):
        log.info("Shutting down proxies...")
        try:
            get_proxy().stop()
        except Exception as e:
            log.error(f"Error stopping StreamProxy: {e}")
        
        try:
            get_range_cache_proxy().stop()
        except Exception as e:
            log.error(f"Error stopping RangeCacheProxy: {e}")
            
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
