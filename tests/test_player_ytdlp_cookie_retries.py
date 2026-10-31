# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""No browser-cookie or YouTube-client retries for errors they cannot fix.

When a site's yt-dlp extractor is broken ("Unable to extract ...; please
report this issue"), the app still tried every browser's cookies, the CLI with
cookies, wider YouTube client pools and the same again in the download
fallback: ~13 yt-dlp runs over 27 s for one item that no cookie could fix.
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

pytest.importorskip("wx")
pytest.importorskip("vlc")
yt_dlp = pytest.importorskip("yt_dlp")

import gui.player as player_mod
from core import discovery, youtube_browser_session, youtube_pytubefix
from gui.player import PlayerFrame

SITE_URL = "https://news.example.com/item/abc123"
YOUTUBE_URL = "https://www.youtube.com/watch?v=abcDEF12345"
EXTRACTOR_BUG = (
    "ERROR: [Example] abc123: Unable to extract embed url; please report this "
    "issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the "
    "appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"
)
BOT_CHECK = "ERROR: [youtube] abcDEF12345: Sign in to confirm you're not a bot"
# yt-dlp asks for a login itself, then appends the bug-report hint (instagram.py).
LOGIN_HINT_BUG = (
    "ERROR: [Instagram] abc123: Instagram sent an empty media response. Check if this "
    "post is accessible in your browser without being logged-in. If it is not, then use "
    "--cookies-from-browser or --cookies for the authentication. See  "
    "https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp  for how "
    "to manually pass cookies. Otherwise, if the post is accessible in browser without "
    "being logged-in, please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= "
    ", filling out the appropriate issue template. Confirm you are on the latest version "
    "using  yt-dlp -U"
)
# expected=False, so it carries the bug-report hint; cookies usually help.
YOUTUBE_NO_PLAYER_RESPONSE = (
    "ERROR: [youtube] abcDEF12345: Failed to extract any player response; please report "
    "this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the "
    "appropriate issue template. Confirm you are on the latest version using  yt-dlp -U"
)
COOKIE_SOURCES = [("chrome",), ("edge",), ("firefox",)]


class _Cfg:
    def get(self, key, default=None):
        return {"ytdlp_cookies_file": ""}.get(key, default)


@pytest.mark.parametrize(
    "message",
    [EXTRACTOR_BUG, "ERROR: Unsupported URL: https://example.com/page"],
)
def test_uncookieable_errors_are_recognised(message):
    assert player_mod._is_ytdlp_uncookieable_error(message)
    assert player_mod._is_ytdlp_uncookieable_error(RuntimeError(message))


def test_login_and_availability_errors_still_try_cookies():
    assert not player_mod._is_ytdlp_uncookieable_error(BOT_CHECK)
    assert not player_mod._is_ytdlp_uncookieable_error("ERROR: Video unavailable")
    assert not player_mod._is_ytdlp_uncookieable_error(LOGIN_HINT_BUG, SITE_URL)


def test_youtube_pages_always_keep_their_cookie_attempts():
    assert player_mod._is_ytdlp_uncookieable_error(YOUTUBE_NO_PLAYER_RESPONSE, SITE_URL)
    for url in (
        YOUTUBE_URL,
        "https://youtu.be/abcDEF12345",
        "https://music.youtube.com/watch?v=abcDEF12345",
        "https://www.youtube-nocookie.com/embed/abcDEF12345",
    ):
        assert player_mod._is_youtube_page_url(url)
        assert not player_mod._is_ytdlp_uncookieable_error(YOUTUBE_NO_PLAYER_RESPONSE, url)
    assert not player_mod._is_youtube_page_url("https://notyoutube.com/watch?v=abcDEF12345")


def _run_resolve(monkeypatch, url, error):
    embedded, cli, after = [], [], []

    class _FakeYDL:
        def __init__(self, opts):
            embedded.append(dict(opts))

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def extract_info(self, *_a, **_kw):
            raise yt_dlp.utils.DownloadError(error)

    def _fake_cli(target, **kwargs):
        cli.append(dict(kwargs, target=target))
        raise RuntimeError(error)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(player_mod, "_extract_ytdlp_info_via_cli", _fake_cli)
    monkeypatch.setattr(discovery, "get_ytdlp_cookie_sources", lambda _url: list(COOKIE_SOURCES))
    monkeypatch.setattr(youtube_pytubefix, "resolve_stream", lambda *_a, **_kw: None)
    monkeypatch.setattr(youtube_browser_session, "bootstrap_youtube_session", lambda *_a, **_kw: None)
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda fn, *a, **kw: after.append((fn, a)))

    p = MagicMock()
    p.config_manager = _Cfg()
    p.is_casting = False
    p.initialized = True
    p._active_load_seq = 1
    p._ytdlp_browser_cookies_dpapi_unavailable = False
    p.maybe_play_ytdlp_via_download.return_value = False
    PlayerFrame._resolve_media_worker(p, 1, url, True, "Title", None)
    return p, embedded, cli, after


def test_extractor_bug_skips_browser_cookies_and_youtube_clients(monkeypatch):
    p, embedded, cli, after = _run_resolve(monkeypatch, SITE_URL, EXTRACTOR_BUG)

    # One anonymous embedded run and one anonymous CLI run, nothing else.
    assert len(embedded) == 1 and "cookiesfrombrowser" not in embedded[0]
    assert len(cli) == 1 and not cli[0].get("cookie_source")
    assert not any(c.get("player_clients") for c in cli)
    # Then the existing VLC-direct last resort for a non-YouTube page.
    assert after and after[-1][0] is p._finish_media_load
    assert after[-1][1][2] == SITE_URL


def test_youtube_login_error_still_tries_cookies_and_wider_clients(monkeypatch):
    _p, embedded, cli, _after = _run_resolve(monkeypatch, YOUTUBE_URL, BOT_CHECK)

    browsers = [o["cookiesfrombrowser"][0] for o in embedded if "cookiesfrombrowser" in o]
    assert browsers == ["chrome", "edge", "firefox"]
    assert [c["cookie_source"][0] for c in cli if c.get("cookie_source")] == ["chrome", "edge", "firefox"]
    assert any(c.get("player_clients") == discovery.YOUTUBE_PLAYER_CLIENTS_FALLBACK for c in cli)


@pytest.mark.parametrize("url, error", [(YOUTUBE_URL, YOUTUBE_NO_PLAYER_RESPONSE), (SITE_URL, LOGIN_HINT_BUG)])
def test_report_this_issue_errors_that_cookies_can_fix_still_try_them(monkeypatch, url, error):
    _p, embedded, cli, _after = _run_resolve(monkeypatch, url, error)

    browsers = [o["cookiesfrombrowser"][0] for o in embedded if "cookiesfrombrowser" in o]
    assert browsers == ["chrome", "edge", "firefox"]
    assert [c["cookie_source"][0] for c in cli if c.get("cookie_source")] == ["chrome", "edge", "firefox"]


class _Res:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _run_download(monkeypatch, tmp_path, url, stderr_for, dpapi_known=False):
    calls = []

    def _fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        source = cmd[cmd.index("--cookies-from-browser") + 1] if "--cookies-from-browser" in cmd else ""
        return _Res(1, stderr=stderr_for(source))

    monkeypatch.setattr(player_mod.subprocess, "run", _fake_run)
    monkeypatch.setattr(discovery, "_resolve_ytdlp_cli_path", lambda: "yt-dlp")
    monkeypatch.setattr(discovery, "get_ytdlp_cookie_sources", lambda _url: list(COOKIE_SOURCES))
    monkeypatch.setattr(player_mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(youtube_pytubefix, "resolve_stream", lambda *_a, **_kw: None)
    monkeypatch.setattr(youtube_browser_session, "bootstrap_youtube_session", lambda *_a, **_kw: None)
    monkeypatch.setattr(player_mod.wx, "CallAfter", lambda *_a, **_kw: None)

    p = MagicMock()
    p.config_manager = _Cfg()
    p._active_load_seq = 7
    p._ytdlp_browser_cookies_dpapi_unavailable = dpapi_known
    p._ytdlp_play_cache_dir.return_value = str(tmp_path)
    p._resolve_printed_filepath.return_value = None
    PlayerFrame._ytdlp_download_and_play_worker(p, 7, url)
    return p, calls


def test_download_fallback_runs_yt_dlp_once_for_an_extractor_bug(monkeypatch, tmp_path):
    _p, calls = _run_download(monkeypatch, tmp_path, SITE_URL, lambda _src: EXTRACTOR_BUG)
    assert len(calls) == 1
    assert "--cookies-from-browser" not in calls[0]


def test_download_fallback_skips_chromium_after_a_session_dpapi_failure(monkeypatch, tmp_path):
    _p, calls = _run_download(
        monkeypatch, tmp_path, YOUTUBE_URL, lambda _src: "ERROR: Video unavailable", dpapi_known=True
    )
    browsers = [c[c.index("--cookies-from-browser") + 1] for c in calls if "--cookies-from-browser" in c]
    assert browsers == ["firefox"]


def test_download_fallback_remembers_dpapi_failure_for_the_session(monkeypatch, tmp_path):
    dpapi = "ERROR: Failed to decrypt with DPAPI. See  https://github.com/yt-dlp/yt-dlp/issues/10927"
    p, _calls = _run_download(
        monkeypatch,
        tmp_path,
        YOUTUBE_URL,
        lambda src: dpapi if src in ("chrome", "edge") else "ERROR: Video unavailable",
    )
    assert p._ytdlp_browser_cookies_dpapi_unavailable is True
