# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GSMArena bodies must keep their section headings and specs list.

Trafilatura drops every <h3> and the specs <ul> from GSMArena's #review-body
in all modes, so the site handler reads the body blocks directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import article_extractor as ax

_PAGE = """
<html><head><title>Widget 9 review - GSMArena.com tests</title></head><body>
<div id="wrapper"><div id="outer"><div id="body">
<div class="main main-review">
<h1 class="article-info-name">Widget 9 review</h1>
<div id="review-body" class="review-body clearfix">
<h3>Introduction</h3>
<p>The Widget 9 arrives with a faster chip and a bigger battery. %s</p>
<p>It keeps the same camera setup as before.</p>
<h3 class="article-blurb-title blurb-title-findings">Widget 9 specs at a glance:</h3>
<ul class="article-blurb article-blurb-findings">
<li><b>Body:</b> 200x100x7mm, 300g; aluminum frame.</li>
<li><b>Display:</b> 9.00" OLED, 144Hz.</li>
</ul>
<h3>Unboxing the Widget 9</h3>
<p>Inside the box you will find the tablet and a cable.</p>
</div></div></div></div></div>
</body></html>
""" % ("Padding sentence to clear the minimum length gate. " * 8)


def test_gsmarena_keeps_headings_and_specs():
    text = ax._extract_site_specific_text(_PAGE, "https://www.gsmarena.com/widget_9-review-1234.php")
    assert "Introduction" in text
    assert "Widget 9 specs at a glance:" in text
    assert "Body: 200x100x7mm, 300g; aluminum frame." in text
    assert "Unboxing the Widget 9" in text
    # Document order preserved: Introduction before Unboxing.
    assert text.index("Introduction") < text.index("Unboxing the Widget 9")


def test_gsmarena_handler_ignores_other_hosts():
    assert ax._extract_site_specific_text(_PAGE, "https://example.com/review") == ""


def test_gsmarena_short_body_falls_through():
    page = "<html><body><div id='review-body'><p>Too short.</p></div></body></html>"
    assert ax._extract_gsmarena_text(page) == ""
