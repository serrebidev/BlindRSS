from __future__ import annotations

from bs4 import BeautifulSoup
import pytest

from core import article_extractor, article_html, utils


SKY_URL = (
    "https://news.sky.com/story/"
    "the-first-solar-eclipse-in-almost-30-years-where-best-to-view-it-13568455"
)

SKY_PAGE = """
<html><head><title>Sky eclipse table</title></head><body><article>
<p>The eclipse will be visible across the country, with timings varying by location.</p>
<p>First contact timings for each city are shown in the interactive table below.</p>
<div class="sdc-article-widget sdc-article-custom-markup">
  <div class="flourish-embed flourish-table"
       data-src="visualisation/29649536?2559214">
    <script src="https://public.flourish.studio/resources/embed.js"></script>
    <noscript><img alt="table visualization"></noscript>
  </div>
</div>
<p>The moon will then move slowly in front of the sun until maximum coverage.</p>
<p>Viewers should use certified eclipse glasses throughout the partial eclipse.</p>
</article></body></html>
"""

FLOURISH_EMBED = r"""
<html><body><script>
var _Flourish_data_column_names = {
  "rows":{"columns":["Stage","Norwich","London, Bristol and Cardiff"]}
},
_Flourish_data_metadata = {
  "rows":{"columns":[
    {"type":"string","output_format_id":"string$arbitrary_string"},
    {"type":"datetime","output_format_id":"datetime$%-I.%M%p"},
    {"type":"datetime","output_format_id":"datetime$%-I.%M%p"}
  ]}
},
_Flourish_data = {"rows":[
  {"columns":["First contact",new Date(-2208923100000),new Date(-2208922980000)]},
  {"columns":["Eclipse maximum",new Date(-2208919740000),new Date(-2208919680000)]},
  {"columns":["End of eclipse",new Date(-2208916560000),new Date(-2208916440000)]}
]};
</script></body></html>
"""


class _Response:
    status_code = 200
    encoding = "utf-8"
    text = FLOURISH_EMBED


@pytest.fixture(autouse=True)
def _table_structure_enabled():
    previous = utils.get_article_structure_options()
    utils.set_article_structure_options({"tables": True})
    try:
        yield
    finally:
        utils.set_article_structure_options(previous)


def _patch_downloads(monkeypatch):
    requested = []

    def fake_page_fetch(url, timeout=20, encoding_override=""):
        return article_extractor._FetchResult(html=SKY_PAGE)

    def fake_embed_fetch(url, **kwargs):
        requested.append((url, kwargs))
        return _Response()

    monkeypatch.setattr(article_extractor, "_fetch_page", fake_page_fetch)
    monkeypatch.setattr(utils, "safe_requests_get", fake_embed_fetch)
    return requested


def test_classic_full_text_expands_sky_flourish_table(monkeypatch):
    requested = _patch_downloads(monkeypatch)

    article = article_extractor.extract_full_article(SKY_URL, max_pages=1)

    assert article is not None
    assert "Table with 3 rows and 3 columns." in article.text
    assert (
        "Row 1: Stage: First contact; Norwich: 6.15PM; "
        "London, Bristol and Cardiff: 6.17PM."
    ) in article.text
    assert "Row 3: Stage: End of eclipse; Norwich: 8.04PM" in article.text
    assert article.text.index("interactive table below") < article.text.index("Row 1:")
    assert article.text.index("Row 3:") < article.text.index("moon will then move")
    assert requested[0][0] == "https://flo.uri.sh/visualisation/29649536/embed"
    assert requested[0][1]["site_cookies"] is False


def test_rich_full_text_expands_sky_flourish_table(monkeypatch):
    _patch_downloads(monkeypatch)

    rendered = article_html.render_full_article_html(SKY_URL, max_pages=1)

    assert rendered is not None
    soup = BeautifulSoup(rendered, "html.parser")
    table = soup.find("table")
    assert table is not None
    assert [cell.get_text(" ", strip=True) for cell in table.select("thead th")] == [
        "Stage",
        "Norwich",
        "London, Bristol and Cardiff",
    ]
    assert all(cell.get("scope") == "col" for cell in table.select("thead th"))
    assert [cell.get_text(" ", strip=True) for cell in table.select("tbody tr:first-child td")] == [
        "First contact",
        "6.15PM",
        "6.17PM",
    ]
    assert "flourish-embed" not in rendered
    assert rendered.index("interactive table below") < rendered.index("<table")
    assert rendered.index("</table>") < rendered.index("moon will then move")


def test_flourish_expansion_is_sky_only(monkeypatch):
    def unexpected_fetch(*args, **kwargs):
        raise AssertionError("Non-Sky pages must not trigger a Flourish follow-up request")

    monkeypatch.setattr(utils, "safe_requests_get", unexpected_fetch)
    assert (
        article_extractor._expand_sky_flourish_tables(
            SKY_PAGE, "https://example.com/article", timeout=5
        )
        == SKY_PAGE
    )

