# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Browser identity resolution (core/user_agents.py)."""

import re

import pytest

from core import user_agents


def _cfg(**values):
    return values.get


def test_presets_cover_the_three_named_browsers():
    keys = {identity.key for identity in user_agents.presets()}
    assert {"chrome_windows", "edge_windows", "firefox_windows"} <= keys


@pytest.mark.parametrize("identity", user_agents.presets(), ids=lambda i: i.key)
def test_every_preset_ua_is_well_formed(identity):
    assert identity.ua.startswith("Mozilla/5.0 (")
    assert re.search(r"(?:Chrome|Firefox)/\d+", identity.ua)


def test_baked_versions_are_current_enough_to_not_read_as_a_bot():
    # The bug this module exists for: a UA frozen at Chrome/124 aged out of
    # every WAF's current-browser window. Guard the floor, not an exact value,
    # so tools/refresh_user_agents.py can keep raising it.
    assert int(user_agents.CHROMIUM_MAJOR) >= 140
    assert int(user_agents.FIREFOX_MAJOR) >= 140


def test_chromium_presets_carry_matching_client_hints():
    chrome = user_agents.preset_by_key("chrome_windows")
    assert chrome is not None
    major = re.search(r"Chrome/(\d+)", chrome.ua).group(1)
    assert f'"Google Chrome";v="{major}"' in chrome.hints["sec-ch-ua"]
    assert chrome.hints["sec-ch-ua-platform"] == '"Windows"'


def test_edge_preset_brands_itself_as_edge():
    edge = user_agents.preset_by_key("edge_windows")
    assert edge is not None
    assert "Edg/" in edge.ua
    assert "Microsoft Edge" in edge.hints["sec-ch-ua"]


def test_firefox_presets_send_no_client_hints():
    # Gecko does not implement UA client hints. Claiming Firefox while sending
    # Chromium hints is a worse fingerprint than the stale string it replaced.
    firefox = user_agents.preset_by_key("firefox_windows")
    assert firefox is not None
    assert firefox.hints == {}


def test_macos_preset_platform_hint_follows_the_ua():
    mac = user_agents.preset_by_key("chrome_macos")
    assert mac is not None
    assert "Macintosh" in mac.ua
    assert mac.hints["sec-ch-ua-platform"] == '"macOS"'


def test_custom_string_is_sent_verbatim():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    identity = user_agents.resolve(_cfg(user_agent_mode="custom", user_agent_custom=ua))
    assert identity.ua == ua
    assert '"Google Chrome";v="150"' in identity.hints["sec-ch-ua"]


def test_custom_firefox_string_does_not_get_chromium_hints():
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:152.0) Gecko/20100101 Firefox/152.0"
    identity = user_agents.resolve(_cfg(user_agent_mode="custom", user_agent_custom=ua))
    assert identity.ua == ua
    assert identity.hints == {}


def test_custom_non_browser_string_gets_no_invented_brands():
    identity = user_agents.resolve(
        _cfg(user_agent_mode="custom", user_agent_custom="MyReader/1.0")
    )
    assert identity.ua == "MyReader/1.0"
    assert identity.hints == {}


def test_blank_custom_falls_back_instead_of_sending_nothing():
    identity = user_agents.resolve(_cfg(user_agent_mode="custom", user_agent_custom="   "))
    assert identity is not None
    assert identity.ua


def test_unknown_mode_falls_back_instead_of_sending_nothing():
    # A key written by a newer build, or a browser since uninstalled.
    identity = user_agents.resolve(_cfg(user_agent_mode="browser_from_the_future"))
    assert identity is not None
    assert identity.ua


def test_missing_config_resolves_to_automatic():
    identity = user_agents.resolve(lambda key, default=None: default)
    assert identity is not None
    assert identity.ua


def test_apply_to_headers_swaps_ua_and_hints_together():
    headers = {
        "User-Agent": "old",
        "sec-ch-ua": "stale-brands",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Accept": "keep-me",
    }
    ua = user_agents.apply_to_headers(_cfg(user_agent_mode="chrome_windows"), headers)
    assert headers["User-Agent"] == ua
    assert headers["sec-ch-ua"] != "stale-brands"
    assert headers["Accept"] == "keep-me"


def test_apply_to_headers_strips_hints_when_switching_to_firefox():
    # The dangerous direction: a leftover Chromium hint under a Gecko UA.
    headers = {
        "User-Agent": "old",
        "sec-ch-ua": '"Chromium";v="150", "Google Chrome";v="150", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    user_agents.apply_to_headers(_cfg(user_agent_mode="firefox_windows"), headers)
    assert "Firefox/" in headers["User-Agent"]
    for name in user_agents.CLIENT_HINT_HEADERS:
        assert name not in headers


def test_apply_to_headers_mutates_in_place_for_shared_references():
    # core.range_cache_proxy does `from core.utils import HEADERS`, so the dict
    # object must be updated rather than replaced.
    headers = {"User-Agent": "old"}
    alias = headers
    user_agents.apply_to_headers(_cfg(user_agent_mode="chrome_windows"), headers)
    assert alias["User-Agent"] == headers["User-Agent"]
    assert alias["User-Agent"] != "old"


def test_utils_default_headers_are_self_consistent():
    from core import utils

    ua = utils.HEADERS["User-Agent"]
    hints = utils.HEADERS.get("sec-ch-ua", "")
    if "Firefox/" in ua:
        assert not hints
    else:
        major = re.search(r"Chrome/(\d+)", ua).group(1)
        assert f'v="{major}"' in hints


def test_detect_installed_returns_usable_identities():
    # Whatever this machine has (possibly nothing) must be well-formed.
    for identity in user_agents.detect_installed():
        assert identity.key.startswith(user_agents.INSTALLED_PREFIX)
        assert identity.ua.startswith("Mozilla/5.0 (")
        assert "(installed)" in identity.label


def test_choices_start_with_automatic_and_have_unique_keys():
    choices = user_agents.choices()
    assert choices[0].key == user_agents.AUTO_MODE
    keys = [c.key for c in choices]
    assert len(keys) == len(set(keys))
