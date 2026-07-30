# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import urllib.error
import urllib.parse
import urllib.request

from core.stream_proxy import StreamProxy


def test_stream_proxy_rejects_requests_without_capability_token(tmp_path):
    media = tmp_path / "private.txt"
    media.write_text("private media", encoding="utf-8")
    proxy = StreamProxy()
    proxy.start()
    try:
        authorized = proxy.get_file_url(str(media))
        parsed = urllib.parse.urlsplit(authorized)
        unauthorized = urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "/file", parsed.query, "")
        )
        try:
            urllib.request.urlopen(unauthorized, timeout=3)
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
        else:
            raise AssertionError("stream proxy accepted a request without its capability token")

        with urllib.request.urlopen(authorized, timeout=3) as response:
            assert response.status == 200
            assert response.read() == b"private media"

        # The token is in the path so relative HLS segment URLs inherit it.
        transcode = urllib.parse.urlsplit(
            proxy.get_transcoded_url("https://example.test/live.ts")
        )
        assert transcode.query == ""
        assert transcode.path.split("/")[1] == proxy._token
    finally:
        proxy.stop()
