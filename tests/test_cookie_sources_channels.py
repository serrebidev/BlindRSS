import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import discovery


def _win_env():
    return {
        "LOCALAPPDATA": r"C:\Users\alice\AppData\Local",
        "APPDATA": r"C:\Users\alice\AppData\Roaming",
    }


def test_build_cookie_sources_detects_edge_and_chrome_channels():
    local = _win_env()["LOCALAPPDATA"]
    present = {
        os.path.join(local, "Google", "Chrome", "User Data"),
        os.path.join(local, "Google", "Chrome Beta", "User Data"),
        os.path.join(local, "Google", "Chrome SxS", "User Data"),  # Canary
        os.path.join(local, "Microsoft", "Edge", "User Data"),
        os.path.join(local, "Microsoft", "Edge Beta", "User Data"),
        os.path.join(local, "Microsoft", "Edge SxS", "User Data"),  # Canary
    }

    with patch("core.discovery.platform.system", return_value="Windows"), patch.dict(
        os.environ, _win_env(), clear=False
    ), patch("core.discovery.os.path.isdir", side_effect=lambda p: p in present):
        sources = discovery._build_cookie_sources()

    # Default installs are passed as the bare keyword; channel variants carry the
    # explicit profile path so yt-dlp reads the right cookie store.
    assert ("chrome",) in sources
    assert ("chrome", os.path.join(local, "Google", "Chrome Beta", "User Data")) in sources
    assert ("chrome", os.path.join(local, "Google", "Chrome SxS", "User Data")) in sources
    assert ("edge",) in sources
    assert ("edge", os.path.join(local, "Microsoft", "Edge Beta", "User Data")) in sources
    assert ("edge", os.path.join(local, "Microsoft", "Edge SxS", "User Data")) in sources


def test_channel_sources_format_with_browser_and_profile():
    src = ("edge", r"C:\Users\alice\AppData\Local\Microsoft\Edge SxS\User Data")
    assert (
        discovery.cookie_arg_for_ytdlp(src)
        == r"edge:C:\Users\alice\AppData\Local\Microsoft\Edge SxS\User Data"
    )
    assert discovery.cookie_arg_for_ytdlp(("firefox",)) == "firefox"
