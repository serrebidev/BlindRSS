# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch

import requests


def test_inoreader_invalid_refresh_token_clears_tokens():
    from providers.inoreader import InoreaderProvider

    cfg = {
        "feed_timeout_seconds": 7,
        "providers": {
            "inoreader": {
                "app_id": "app",
                "app_key": "secret",
                "token": "expired-access",
                "refresh_token": "bad-refresh",
                # Make the token look stale so refresh is attempted.
                "token_expires_at": 1,
            }
        },
    }

    provider = InoreaderProvider(cfg)

    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Invalid refresh token",
    }

    err = requests.HTTPError("400 Client Error: Bad Request")
    err.response = fake_resp

    with patch("providers.inoreader.inoreader_oauth.refresh_access_token", side_effect=err):
        assert provider.get_feeds() == []

    p_cfg = cfg["providers"]["inoreader"]
    assert p_cfg["token"] == ""
    assert p_cfg["refresh_token"] == ""
    assert int(p_cfg["token_expires_at"] or 0) == 0

