# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Accessible table preservation in full-text extraction and HTML-to-text.

Full-text extraction used to drop article tables outright (trafilatura ran
with include_tables=False), so a story built around a data table lost it
(e.g. windowslatest.com's Patch Tuesday CVE-count tables). The reader pane is
a plain text control, so tables can't be shown structurally for NVDA either;
instead each data row is linearized as "Header: value; Header: value." lines
that read naturally with line navigation.
"""

from bs4 import BeautifulSoup

from core import article_extractor
from core.utils import format_table_text, html_to_text, replace_tables_with_text


def _table(html: str):
    return BeautifulSoup(html, "html.parser").find("table")


HEADERED_TABLE = """
<table>
  <caption>Windows 11 flaws patched</caption>
  <thead><tr><th>Year</th><th>Flaws</th></tr></thead>
  <tbody>
    <tr><td>2025</td><td>140</td></tr>
    <tr><td>2026</td><td>570</td></tr>
  </tbody>
</table>
"""


# --------------------------------------------------------------------------- #
# format_table_text
# --------------------------------------------------------------------------- #

def test_headered_table_reads_as_header_value_rows():
    text = format_table_text(_table(HEADERED_TABLE))
    assert text.split("\n") == [
        "Table with 2 rows and 2 columns: Windows 11 flaws patched.",
        "Row 1: Year: 2025; Flaws: 140.",
        "Row 2: Year: 2026; Flaws: 570.",
        "End of table.",
    ]


def test_headerless_table_reads_cells_in_order():
    text = format_table_text(_table(
        "<table><tr><td>2025</td><td>140</td></tr>"
        "<tr><td>2026</td><td>570</td></tr></table>"
    ))
    assert text.split("\n") == [
        "Table with 2 rows and 2 columns.",
        "Row 1: 2025; 140.",
        "Row 2: 2026; 570.",
        "End of table.",
    ]


def test_thead_td_cells_still_count_as_headers():
    text = format_table_text(_table(
        "<table><thead><tr><td>Year</td><td>Flaws</td></tr></thead>"
        "<tr><td>2026</td><td>570</td></tr></table>"
    ))
    assert "Row 1: Year: 2026; Flaws: 570." in text


def test_layout_table_with_block_content_is_left_alone():
    assert format_table_text(_table(
        "<table><tr><td><p>Article body paragraph laid out in a table.</p></td></tr></table>"
    )) == ""


def test_huge_prose_cell_is_left_alone():
    prose = "word " * 200
    assert format_table_text(_table(f"<table><tr><td>{prose}</td><td>x</td></tr></table>")) == ""


def test_single_column_table_reads_as_plain_lines():
    text = format_table_text(_table(
        "<table><tr><td>First point</td></tr><tr><td>Second point</td></tr></table>"
    ))
    assert text == "First point\nSecond point"


def test_row_with_mismatched_cell_count_falls_back_to_plain_cells():
    text = format_table_text(_table(
        "<table><tr><th>A</th><th>B</th></tr>"
        "<tr><td>1</td><td>2</td></tr>"
        "<tr><td>only one cell</td></tr></table>"
    ))
    assert "Row 1: A: 1; B: 2." in text
    assert "Row 2: only one cell." in text


def test_empty_table_returns_empty():
    assert format_table_text(_table("<table></table>")) == ""


# --------------------------------------------------------------------------- #
# html_to_text (feed content path)
# --------------------------------------------------------------------------- #

def test_html_to_text_linearizes_data_tables():
    text = html_to_text(f"<div><p>Intro paragraph.</p>{HEADERED_TABLE}<p>After.</p></div>")
    assert "Intro paragraph." in text
    assert "Row 1: Year: 2025; Flaws: 140." in text
    assert "End of table." in text
    assert text.index("Intro paragraph.") < text.index("Row 1:") < text.index("After.")


def test_nested_data_table_inside_layout_table_is_formatted():
    html = f"<table><tr><td><p>layout shell</p>{HEADERED_TABLE}</td></tr></table>"
    soup = BeautifulSoup(html, "html.parser")
    blocks = replace_tables_with_text(soup)
    assert len(blocks) == 1
    assert "Row 2: Year: 2026; Flaws: 570." in blocks[0]
    # The outer layout table must be untouched.
    assert soup.find("table") is not None


# --------------------------------------------------------------------------- #
# extractor pipeline
# --------------------------------------------------------------------------- #

ARTICLE_PAGE = f"""
<html><head><title>Patch story</title></head><body>
<article>
<h1>Record number of flaws patched</h1>
<p>{"Microsoft patched a record number of security flaws this month. " * 6}</p>
<p>The table below shows how the counts have grown over the years.</p>
{HEADERED_TABLE}
<p>{"Security researchers attribute the growth to AI-assisted bug hunting. " * 6}</p>
</article>
</body></html>
"""


def test_extract_from_html_keeps_table_rows_in_place():
    art = article_extractor.extract_from_html(ARTICLE_PAGE, "https://example.com/patch-story")
    assert art is not None
    text = art.text
    assert "Row 1: Year: 2025; Flaws: 140." in text
    assert "Row 2: Year: 2026; Flaws: 570." in text
    assert "End of table." in text
    # Placement: the table sits between the paragraph that references it and the closer.
    assert text.index("table below") < text.index("Row 1:") < text.index("Security researchers")


def test_merge_texts_keeps_short_table_rows_and_repeated_markers():
    page = (
        "A real paragraph long enough to clear the twenty-five character floor.\n"
        "Table with 1 rows and 2 columns.\n"
        "Row 1: A: 1; B: 2.\n"
        "End of table.\n"
        "Another real paragraph long enough to clear the length floor easily.\n"
        "Table with 1 rows and 2 columns.\n"
        "Row 1: C: 3; D: 4.\n"
        "End of table."
    )
    merged = article_extractor._merge_texts([page])
    assert merged.count("End of table.") == 2
    assert "Row 1: A: 1; B: 2." in merged
    assert "Row 1: C: 3; D: 4." in merged


def test_duplicate_table_markup_yields_single_block():
    # Sites ship the same table twice (desktop + mobile markup); only one
    # linearized copy must survive (seen live on windowslatest.com).
    text = html_to_text(f"<div>{HEADERED_TABLE}{HEADERED_TABLE}</div>")
    assert text.count("Row 2: Year: 2026; Flaws: 570.") == 1
    assert text.count("End of table.") == 1


def test_merge_texts_dedupes_identical_table_across_pages():
    block = (
        "Table with 1 rows and 2 columns.\n"
        "Row 1: A: 1; B: 2.\n"
        "End of table."
    )
    page1 = "First page paragraph long enough to clear the length floor easily.\n" + block
    page2 = "Second page paragraph long enough to clear the length floor easily.\n" + block
    merged = article_extractor._merge_texts([page1, page2])
    assert merged.count("Row 1: A: 1; B: 2.") == 1
    assert merged.count("End of table.") == 1


def test_append_missing_tables_scopes_to_dom_kept_tables():
    block = "Table with 1 rows and 2 columns.\nRow 1: Year: 2026; Flaws: 570.\nEnd of table."
    junk = "Table with 1 rows and 2 columns.\nRow 1: Sidebar: junk.\nEnd of table."
    dom_text = "Body paragraph.\n" + block
    json_text = "Body paragraph from JSON-LD articleBody without the table."

    patched = article_extractor._append_missing_tables(json_text, [block, junk], dom_text)
    assert "Row 1: Year: 2026; Flaws: 570." in patched
    # The sidebar table was not part of the DOM-scoped article body: never appended.
    assert "Sidebar: junk" not in patched

    # Already present -> unchanged.
    again = article_extractor._append_missing_tables(patched, [block], dom_text)
    assert again == patched
