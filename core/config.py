import copy
import json
import os
import sys
import logging

log = logging.getLogger(__name__)

# Install directory (where the executable or main script lives).
# On macOS frozen builds this is inside the .app bundle, which gets
# replaced on upgrade — that is why we also support a user-data path.
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))


def _user_data_dir() -> str:
    """OS-appropriate per-user data directory for BlindRSS."""
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "BlindRSS")


USER_DATA_DIR = _user_data_dir()

CONFIG_FILENAME = "config.json"
APP_CONFIG_PATH = os.path.join(APP_DIR, CONFIG_FILENAME)
USER_CONFIG_PATH = os.path.join(USER_DATA_DIR, CONFIG_FILENAME)

# Active config path resolved at ConfigManager init. Defaults to APP_DIR until then.
CONFIG_FILE = APP_CONFIG_PATH


def _default_config_location() -> str:
    """Default storage location for fresh installs."""
    if sys.platform == "darwin" and getattr(sys, "frozen", False):
        return "user_data"
    return "app_folder"


def _path_for_location(location: str) -> str:
    return USER_CONFIG_PATH if location == "user_data" else APP_CONFIG_PATH

DEFAULT_CONFIG = {
    "max_downloads": 32,
    "auto_download_podcasts": False,
    "auto_download_period": "unlimited",
    "refresh_interval": 300,  # seconds
    # Refresh is primarily network-bound, but over-aggressive parallelism causes
    # CPU spikes and can actually slow large OPML refreshes when a handful of
    # feeds stall or throttle. Keep the default balanced.
    "max_concurrent_refreshes": 6,
    "miniflux_targeted_refresh_workers": 8,
    "per_host_max_connections": 2,
    "feed_timeout_seconds": 15,
    "feed_retry_attempts": 1,
    "playback_resolve_timeout_s": 4.0,
    "active_provider": "local",
    "debug_mode": False,
    "refresh_on_startup": True,
    "prompt_missing_dependencies_on_startup": True,
    "auto_check_updates": True,
    "start_on_windows_login": False,
    "sounds_enabled": True,
    "sound_refresh_complete": "sounds/refresh_complete.wav",
    "sound_refresh_error": "sounds/refresh_error.wav",
    "windows_notifications_enabled": False,
    "windows_notifications_include_feed_name": True,
    "windows_notifications_max_per_refresh": 0,  # 0 = unlimited
    "windows_notifications_show_summary_when_capped": True,
    "windows_notifications_excluded_feeds": [],
    "preferred_soundcard": "",  # empty => use current OS default output device
    "skip_silence": True,
    "silence_vad_aggressiveness": 2,  # 0-3 (3 = most aggressive)
    "silence_vad_frame_ms": 30,  # 10, 20, or 30
    "silence_skip_threshold_db": -38.0,  # used only as RMS fallback
    "silence_skip_min_ms": 700,
    "silence_skip_window_ms": 25,
    "silence_skip_padding_ms": 60,
    "silence_skip_merge_gap_ms": 260,
    "silence_skip_resume_backoff_ms": 360,
    "silence_skip_retrigger_backoff_ms": 1400,
    "close_to_tray": True,
    "minimize_to_tray": True,
    "start_maximized": False,
    "max_cached_views": 15,
    "cache_full_text": False,
    "playback_speed": 1.0,
    "volume": 100,
    "volume_step": 5,
    "seek_back_ms": 10000,
    "seek_forward_ms": 10000,
    "resume_playback": True,
    "resume_save_interval_s": 15,
    "resume_back_ms": 10000,
    "resume_min_ms": 0,
    "resume_complete_threshold_ms": 60000,
    "show_player_on_play": False,
    "vlc_network_caching_ms": 1000,
    "vlc_local_proxy_network_caching_ms": 1000,  # keep VLC buffering low for local range-cache proxy
    "vlc_local_proxy_file_caching_ms": 1000,  # keep VLC buffering low for local range-cache proxy
    "range_cache_enabled": False,
    "range_cache_apply_all_hosts": True,  # apply local range-cache proxy to all HTTP(S) hosts
    "range_cache_initial_burst_kb": 8192,  # initial background burst (KB) - 8 MB default
    "range_cache_initial_inline_prefetch_kb": 1024,  # small inline prefetch cushion per seek/read (KB) - 1 MB default
    "range_cache_prefetch_kb": 32768,  # per seek/read; larger reduces round-trips on high latency
    "range_cache_inline_window_kb": 4096,  # max bytes served per VLC request; smaller = lower seek latency
    "range_cache_hosts": [],  # allowlist when range_cache_apply_all_hosts is False
    "range_cache_dir": "",  # empty => use OS temp directory
    "range_cache_background_download": False,  # download ahead in background to make later seeks faster
    "range_cache_background_chunk_kb": 16384,  # chunk size for background download
    "range_cache_debug": False,  # verbose local proxy debug logs (PROXY_DEBUG)
    "downloads_enabled": False,
    "download_path": os.path.join(APP_DIR, "podcasts"),
    "download_retention": "Unlimited",
    "article_retention": "Unlimited",
    "persistent_searches": [],
    "show_search_field": True,
    "search_mode": "title_content",
    # Storage location for config.json (and, on next startup, rss.db).
    # "app_folder" = alongside the executable, "user_data" = OS user data folder.
    "data_location": _default_config_location(),
    # Translation (future/experimental feature wiring)
    "translation_enabled": False,
    "translation_provider": "grok",
    "translation_target_language": "en",
    "translation_grok_model": "",
    "translation_grok_api_key": "",
    "translation_groq_model": "",
    "translation_groq_api_key": "",
    "translation_openai_model": "",
    "translation_openai_api_key": "",
    "translation_openrouter_model": "",
    "translation_openrouter_api_key": "",
    "translation_gemini_model": "",
    "translation_gemini_api_key": "",
    "translation_qwen_model": "",
    "translation_qwen_api_key": "",
    "article_sort_by": "date",
    "article_sort_ascending": False,
    "providers": {
        "local": {
            "feeds": []  # List of feed URLs/data
        },
        "theoldreader": {
            "email": "",
            "password": ""
        },
        "miniflux": {
            "url": "",
            "api_key": ""
        },
        "inoreader": {
            "token": "",
            "app_id": "",
            "app_key": "",
            "refresh_token": "",
            "token_expires_at": 0,
            # Cache subscription/category metadata longer than local RSS providers to avoid
            # exhausting Inoreader's low per-app API quotas during periodic UI refresh checks.
            "metadata_cache_ttl_seconds": 3600,
            # Short-lived per-view article cache to absorb repeated UI paging/selection requests.
            "article_cache_ttl_seconds": 90,
            # stream/contents page size; larger values reduce request count at the expense of payload size.
            "article_request_page_size": 100,
            # Inoreader redirect URIs are typically required to be HTTPS. For localhost callbacks we
            # use an HTTPS URL and complete authorization by pasting the redirected URL back into
            # BlindRSS (no local TLS server needed).
            "redirect_uri": "https://127.0.0.1:18423/inoreader/oauth",
        },
        "bazqux": {
            "email": "",
            "password": ""
        }
    }
}


import threading


def _resolve_config_path() -> tuple[str, str]:
    """
    Decide where config.json should be read from and return (path, location_tag).

    Preference: user_data location if config exists there, else app_folder if
    config exists there, else the OS default location (which may not yet exist).
    """
    user_exists = os.path.exists(USER_CONFIG_PATH)
    app_exists = os.path.exists(APP_CONFIG_PATH)
    if user_exists and app_exists:
        # Prefer whichever was modified more recently.
        try:
            if os.path.getmtime(USER_CONFIG_PATH) >= os.path.getmtime(APP_CONFIG_PATH):
                return USER_CONFIG_PATH, "user_data"
            return APP_CONFIG_PATH, "app_folder"
        except OSError:
            return USER_CONFIG_PATH, "user_data"
    if user_exists:
        return USER_CONFIG_PATH, "user_data"
    if app_exists:
        return APP_CONFIG_PATH, "app_folder"
    default_loc = _default_config_location()
    return _path_for_location(default_loc), default_loc


def _ensure_parent_dir(path: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass


def get_data_dir() -> str:
    """Directory where config.json lives. Currently also the preferred dir for rss.db."""
    return os.path.dirname(CONFIG_FILE) or APP_DIR


class ConfigManager:
    def __init__(self):
        self._lock = threading.Lock()
        # Honor a caller-set CONFIG_FILE (e.g., tests that monkeypatch it).
        current = globals().get("CONFIG_FILE", None)
        standard_paths = {
            os.path.abspath(APP_CONFIG_PATH),
            os.path.abspath(USER_CONFIG_PATH),
        }
        if current and os.path.abspath(current) not in standard_paths:
            self.config_path = current
            self.data_location = "app_folder"
        else:
            self.config_path, self.data_location = _resolve_config_path()
        global CONFIG_FILE
        CONFIG_FILE = self.config_path
        self.config = self.load_config()
        # Make sure the config records its current physical location.
        try:
            if str(self.config.get("data_location", "")) != self.data_location:
                self.config["data_location"] = self.data_location
                self.save_config()
        except Exception:
            log.exception("Failed to record data_location in config")
        try:
            if self._apply_migrations():
                self.save_config()
        except Exception:
            log.exception("Failed to apply config migrations")

    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with self._lock:
                    with open(self.config_path, 'r') as f:
                        loaded = json.load(f)
                        return self._apply_defaults(loaded)
            except Exception as e:
                log.error(f"Error loading config: {e}")
                return copy.deepcopy(DEFAULT_CONFIG)
        return copy.deepcopy(DEFAULT_CONFIG)

    def _apply_defaults(self, cfg: dict) -> dict:
        """
        Merge any missing default keys into an existing config without clobbering
        user settings. Ensures new options (e.g., skip_silence) are present.
        """
        def merge(defaults, target):
            for key, val in defaults.items():
                if isinstance(val, dict):
                    if key not in target or not isinstance(target.get(key), dict):
                        target[key] = {}
                    merge(val, target[key])
                else:
                    target.setdefault(key, val)
        merged = cfg if isinstance(cfg, dict) else {}
        merge(DEFAULT_CONFIG, merged)
        return merged

    def _apply_migrations(self) -> bool:
        """
        Apply in-place migrations for older config.json files.

        Returns True if any changes were made.
        """
        cfg = self.config
        if not isinstance(cfg, dict):
            return False

        changed = False

        # v1.49.x: resume_min_ms default changed from 20000ms -> 0ms.
        # Migrate old default values so users get consistent behavior after upgrade.
        try:
            resume_min_ms = cfg.get("resume_min_ms", None)
            if resume_min_ms is not None and int(resume_min_ms) == 20000:
                cfg["resume_min_ms"] = 0
                changed = True
        except (TypeError, ValueError):
            log.warning("Could not migrate 'resume_min_ms' due to invalid value in config.json; leaving it as is.")

        # v1.63.x+: refresh defaults were tuned multiple times.
        # Only migrate when the values still match a known untouched default set.
        try:
            max_concurrent = cfg.get("max_concurrent_refreshes", None)
            per_host = cfg.get("per_host_max_connections", None)
            feed_retries = cfg.get("feed_retry_attempts", None)
            if max_concurrent is not None and per_host is not None and feed_retries is not None:
                if (int(max_concurrent), int(per_host), int(feed_retries)) in (
                    (10, 4, 5),
                    (12, 4, 5),
                    (6, 2, 5),
                    (3, 1, 5),
                    (8, 2, 1),
                ):
                    cfg["max_concurrent_refreshes"] = int(DEFAULT_CONFIG["max_concurrent_refreshes"])
                    cfg["per_host_max_connections"] = int(DEFAULT_CONFIG["per_host_max_connections"])
                    cfg["feed_retry_attempts"] = int(DEFAULT_CONFIG["feed_retry_attempts"])
                    changed = True
        except (TypeError, ValueError):
            log.warning(
                "Could not migrate refresh defaults due to invalid values in config.json; leaving them as is."
            )

        return bool(changed)

    def save_config(self):
        try:
            with self._lock:
                _ensure_parent_dir(self.config_path)
                with open(self.config_path, 'w') as f:
                    json.dump(self.config, f, indent=4)
        except Exception as e:
            log.error(f"Error saving config: {e}")

    def get(self, key, default=None):
        return self.config.get(key, default)

    def set(self, key, value):
        self.config[key] = value
        self.save_config()

    def get_provider_config(self, provider_name):
        return self.config.get("providers", {}).get(provider_name, {})

    def update_provider_config(self, provider_name, data):
        if "providers" not in self.config:
            self.config["providers"] = {}
        if provider_name not in self.config["providers"]:
            self.config["providers"][provider_name] = {}
        self.config["providers"][provider_name].update(data)
        self.save_config()

    # --- Data location management --------------------------------------------

    def change_data_location(self, new_location: str) -> tuple[bool, str]:
        """
        Move config.json to the requested location and update internal state.

        Returns (ok, message). The DB file is not moved here because it may be
        open; it will be handled on next startup if needed.
        """
        new_location = "user_data" if new_location == "user_data" else "app_folder"
        if new_location == self.data_location:
            return True, "No change."

        new_path = _path_for_location(new_location)
        old_path = self.config_path

        try:
            _ensure_parent_dir(new_path)
            with self._lock:
                self.config["data_location"] = new_location
                with open(new_path, 'w') as f:
                    json.dump(self.config, f, indent=4)
        except Exception as e:
            log.exception("Failed to write config to new location")
            return False, f"Could not write config at new location: {e}"

        # Remove the old file so future resolution is unambiguous.
        try:
            if os.path.exists(old_path) and os.path.abspath(old_path) != os.path.abspath(new_path):
                os.remove(old_path)
        except Exception:
            log.exception("Failed to remove old config file at %s", old_path)

        self.config_path = new_path
        self.data_location = new_location
        global CONFIG_FILE
        CONFIG_FILE = new_path
        return True, f"Config moved to {new_path}."

    @staticmethod
    def location_paths() -> dict:
        """Helper for UIs to display the two candidate locations."""
        return {
            "app_folder": APP_CONFIG_PATH,
            "user_data": USER_CONFIG_PATH,
        }
