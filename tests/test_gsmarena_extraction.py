# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""GSMArena bodies must keep their section headings and specs list.

Trafilatura drops every <h3> and the specs <ul> from GSMArena's #review-body
in all modes, so the site handler reads the body blocks directly.
"""
import os
import sys
from types import SimpleNamespace

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import article_extractor as ax
from core import article_html

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


def _battery_page(row_count=502):
    rows = [
        "<tr><td>Sony Xperia 10 VIII</td><td>13:37h</td><td>31:55h</td>"
        "<td>14:43h</td><td>23:35h</td><td>5:52h</td><td>13:37h</td></tr>"
    ]
    for number in range(row_count - 2):
        rows.append(
            f"<tr><td>Test phone {number}</td><td>10:00h</td><td>20:00h</td>"
            "<td>10:00h</td><td>10:00h</td><td>10:00h</td><td>10:00h</td></tr>"
        )
    rows.append(
        "<tr><td>Realme P4 Power</td><td>25:35h</td><td>61:08h</td>"
        "<td>24:46h</td><td>34:33h</td><td>13:19h</td><td>25:35h</td></tr>"
    )
    return (
        "<html><head><title>Battery life test v2.0</title></head><body>"
        "<div class='article-body'><h1>Battery life test results v2.0</h1>"
        "<p>This page puts together the stats for every phone in the current "
        "battery test. Use the results to compare each area of performance.</p>"
        "<table id='battery-table'><thead><tr><th>Phone</th><th>Active use score</th>"
        "<th>Calls</th><th>Web</th><th>Video</th><th>Game</th><th>Your score</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div></body></html>"
    )


_BATTERY_URL = "https://www.gsmarena.com/battery-test-v2.php3"


def test_gsmarena_large_battery_table_is_kept_and_uses_browser_order():
    text = ax._extract_text_any(_battery_page(), _BATTERY_URL)

    assert "Table with 502 rows and 7 columns." in text
    assert "Row 1: Phone: Realme P4 Power;" in text
    assert text.index("Realme P4 Power") < text.index("Sony Xperia 10 VIII")


def test_gsmarena_rich_battery_table_uses_browser_order(monkeypatch):
    monkeypatch.setattr(
        ax, "_fetch_page", lambda *_args, **_kwargs: SimpleNamespace(html=_battery_page())
    )
    monkeypatch.setattr(ax, "_find_next_page", lambda *_args, **_kwargs: None)

    rendered = article_html.render_full_article_html(_BATTERY_URL, max_pages=1)
    soup = BeautifulSoup(rendered, "html.parser")
    rows = soup.select("article table tbody tr")

    assert len(rows) == 502
    assert rows[0].find("td").get_text(" ", strip=True) == "Realme P4 Power"
    assert rows[-1].find("td").get_text(" ", strip=True) == "Test phone 499"
