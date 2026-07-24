# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

from core import utils


def test_html_text_preview_keeps_visible_text_and_skips_code():
    html = """
    <style>.hidden { display: none }</style>
    <p>Hello &amp; <b>world</b>.</p>
    <script>window.secret = 'not visible';</script>
    <p>More text</p>
    """

    assert utils.html_to_text_preview(html, max_chars=200) == (
        "Hello & world . More text"
    )


def test_html_text_preview_is_bounded_for_large_articles():
    html = "<p>" + ("alpha beta " * 10_000) + "</p><p>unreachable tail</p>"

    preview = utils.html_to_text_preview(html, max_chars=80)

    assert len(preview) <= 80
    assert preview.startswith("alpha beta alpha beta")
    assert "unreachable" not in preview


def test_html_text_preview_handles_plain_text_without_full_parser():
    assert utils.html_to_text_preview("  plain\n text  ", max_chars=20) == "plain text"
