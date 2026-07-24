# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import inoreader_oauth


def test_parse_oauth_redirect_full_url():
    code, state, err = inoreader_oauth.parse_oauth_redirect(
        "https://127.0.0.1:18423/inoreader/oauth?code=abc123&state=st456"
    )
    assert code == "abc123"
    assert state == "st456"
    assert err is None


def test_parse_oauth_redirect_query_string():
    code, state, err = inoreader_oauth.parse_oauth_redirect("code=abc123&state=st456")
    assert code == "abc123"
    assert state == "st456"
    assert err is None


def test_parse_oauth_redirect_bare_code():
    code, state, err = inoreader_oauth.parse_oauth_redirect("abc123")
    assert code == "abc123"
    assert state is None
    assert err is None


def test_get_redirect_uri_defaults_to_https():
    uri = inoreader_oauth.get_redirect_uri()
    assert uri.startswith("https://")
