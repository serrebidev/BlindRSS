# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import json
import os

from core import browser_feed, discovery, youtube_browser_session as ybs


def test_cookie_file_contains_only_youtube_domains(tmp_path):
    path = ybs._write_netscape_cookie_file(
        [
            {
                "domain": ".youtube.com",
                "path": "/",
                "secure": True,
                "expiry": 2000000000,
                "name": "VISITOR_INFO1_LIVE",
                "value": "visitor",
            },
            {
                "domain": ".example.com",
                "path": "/",
                "name": "session",
                "value": "must-not-leak",
            },
        ],
        str(tmp_path / "youtube.txt"),
    )

    text = open(path, encoding="utf-8").read()
    assert ".youtube.com" in text
    assert "VISITOR_INFO1_LIVE" in text
    assert "example.com" not in text
    assert "must-not-leak" not in text
    assert not os.path.exists(path + ".tmp")


def test_player_client_arg_can_include_browser_visitor_data():
    arg = discovery.youtube_player_client_arg(
        discovery.YOUTUBE_PLAYER_CLIENTS_FALLBACK,
        visitor_data="visitor%3D%3D",
    )
    assert ";visitor_data=visitor%3D%3D" in arg
    assert arg.startswith("youtube:player_client=")


def test_player_client_arg_rejects_extractor_arg_injection():
    arg = discovery.youtube_player_client_arg(visitor_data="good;player_client=bad")
    assert "visitor_data" not in arg
    assert "player_client=bad" not in arg


def test_bootstrap_uses_dedicated_hidden_profile_and_writes_session(
    tmp_path,
    monkeypatch,
):
    class _FakeSB:
        def __init__(self):
            self.target = ""

        def activate_cdp_mode(self, target):
            self.target = target

        def execute_script(self, _script):
            return json.dumps(
                {
                    "visitor": "visitor%3D%3D",
                    "status": "OK",
                    "title": "Example video",
                    "ua": "Mozilla/5.0 Test Chrome",
                }
            )

        def get_cookies(self):
            return [
                {
                    "domain": ".youtube.com",
                    "path": "/",
                    "secure": True,
                    "name": "YSC",
                    "value": "abc",
                }
            ]

    fake_sb = _FakeSB()
    monkeypatch.setattr(ybs.config_mod, "get_data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(browser_feed, "_browser_options", lambda profile, proxy: {"profile": profile})
    monkeypatch.setattr(browser_feed, "_redirect_seleniumbase_work_files", lambda _runtime: None)
    monkeypatch.setattr(browser_feed, "_session_locked", lambda _SB, _options: fake_sb)
    monkeypatch.setattr(browser_feed, "_cancelled", lambda _event: False)
    monkeypatch.setattr(browser_feed, "_session", None)
    ybs._clear_cache_for_tests()

    session = ybs.bootstrap_youtube_session(
        "https://www.youtube.com/watch?v=A3TU_p5kLJI",
        timeout_s=15,
    )

    assert session is not None
    assert fake_sb.target == "https://www.youtube.com/watch?v=A3TU_p5kLJI"
    assert session.visitor_data == "visitor%3D%3D"
    assert session.user_agent == "Mozilla/5.0 Test Chrome"
    assert os.path.isfile(session.cookie_file)
    assert "youtube_browser_profile" in str(
        browser_feed._browser_options(
            os.path.join(str(tmp_path), "youtube_browser_profile"), None
        )["profile"]
    )
    ybs._clear_cache_for_tests()
