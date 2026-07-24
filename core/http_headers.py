# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Shared helpers for building HTTP header dictionaries from channel metadata."""

from typing import Dict, Optional


def channel_http_headers(channel: Optional[Dict[str, str]]) -> Dict[str, object]:
    """Collect per-channel HTTP headers for players/casters."""
    headers: Dict[str, object] = {}
    if not channel:
        return headers

    def _copy(keys, target: str) -> None:
        for key in keys:
            val = channel.get(key)
            if val:
                headers[target] = val
                return

    _copy(["http-user-agent"], "user-agent")
    _copy(["http-referrer", "http-referer"], "referer")
    _copy(["http-origin"], "origin")
    _copy(["http-cookie"], "cookie")
    _copy(["http-authorization"], "authorization")
    _copy(["http-accept"], "accept")

    extra = channel.get("http-headers")
    if isinstance(extra, list):
        headers["_extra"] = [str(h) for h in extra if h]

    return headers
