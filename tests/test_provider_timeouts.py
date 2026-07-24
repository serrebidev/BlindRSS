# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from unittest.mock import MagicMock, patch


def test_inoreader_request_sets_timeout_by_default():
    from providers.inoreader import InoreaderProvider

    provider = InoreaderProvider({"providers": {"inoreader": {}}, "feed_timeout_seconds": 7})

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.headers = {}
    fake_resp.raise_for_status.return_value = None

    with patch("providers.inoreader.requests.request", return_value=fake_resp) as mock_req:
        provider._request("get", "https://example.com/api/0/subscription/list", params={"output": "json"})

    assert mock_req.call_args.kwargs.get("timeout") == 7


def test_theoldreader_login_passes_timeout():
    from providers.theoldreader import TheOldReaderProvider

    provider = TheOldReaderProvider(
        {
            "feed_timeout_seconds": 9,
            "providers": {"theoldreader": {"email": "user@example.com", "password": "pw"}},
        }
    )

    fake_resp = MagicMock()
    fake_resp.status_code = 200
    fake_resp.text = "Auth=token123\n"
    fake_resp.json.side_effect = ValueError("not json")

    with patch("providers.theoldreader.requests.post", return_value=fake_resp) as mock_post:
        assert provider._login() is True

    assert mock_post.call_args.kwargs.get("timeout") == 9


def test_bazqux_login_passes_timeout():
    from providers.bazqux import BazQuxProvider

    provider = BazQuxProvider(
        {
            "feed_timeout_seconds": 11,
            "providers": {"bazqux": {"email": "user", "password": "pw"}},
        }
    )

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = {"Auth": "token123"}

    provider.session.post = MagicMock(return_value=fake_resp)

    assert provider._login() is True
    assert provider.session.post.call_args.kwargs.get("timeout") == 11

