"""Offline regressions for Ars Technica's split article body."""

import pytest
from bs4 import BeautifulSoup

from core import article_extractor as ax, article_html


URL = "https://arstechnica.com/gadgets/2026/10/starlink/"
LEAD = (
    "Ukraine's engineers are adapting their communications equipment to keep "
    "essential services working under difficult battlefield conditions. " * 5
) + "The engineer specializes in repairing Starlink dishes."
END = "The final section explains why communications resilience matters."
PAGE = (
    '<html><head><title>Satellite communications</title></head><body>'
    '<nav>Site navigation</nav><article class="double-column h-entry">'
    '<header><h1>Satellite communications</h1></header>'
    '<div class="grid"><div><div class="post-content post-content-double">'
    f'<p>{LEAD}</p><div class="ars-interlude-container"><p>Interlude promotion</p>'
    '</div></div></div><aside>Sidebar promotion</aside></div>'
    '<div class="grid"><div><div class="post-content post-content-double">'
    '<div class="page-anchor-wrapper">Page tracking label</div>'
    '<h2>Navigation alternatives</h2><p>Engineers built a '
    '<a href="/technology/backup/">backup system</a> for these missions.</p>'
    '<figure><img src="/image.jpg" alt="Communications equipment">'
    '<figcaption>Equipment in the field.</figcaption></figure>'
    '</div></div></div>'
    '<div class="grid"><div><div class="post-content post-content-double">'
    f'<blockquote><p>{END}</p></blockquote>'
    '<script>unsafeScript()</script></div></div></div>'
    '<section class="author-bio"><p>Author biography</p></section>'
    '<section class="comments"><p>Reader comments</p></section></article>'
    '<article><div class="post-content"><p>Unrelated story</p></div></article>'
    '</body></html>'
)


@pytest.mark.parametrize("reader", ["classic", "rich"])
def test_all_body_sections_survive(reader, monkeypatch):
    monkeypatch.setattr(ax, "_fetch_page", lambda *_a, **_kw: ax._FetchResult(html=PAGE))
    if reader == "classic":
        result = ax.extract_full_article(URL)
        assert result is not None
        text = result.text
    else:
        result = article_html.clean_article_html(PAGE, URL)
        body = BeautifulSoup(result, "html.parser")
        text = body.get_text(" ", strip=True)
        assert body.find("h2").get_text() == "Navigation alternatives"
        assert body.find("a")["href"] == "https://arstechnica.com/technology/backup/"
        assert body.find("img")["alt"] == "Communications equipment"
        assert body.find("blockquote") is not None
        assert body.find("script") is None
    assert "repairing Starlink dishes." in text
    assert text.count(END) == 1
    assert text.index("repairing Starlink dishes.") < text.index("Navigation alternatives") < text.index(END)
    for junk in (
        "Interlude promotion", "Page tracking label", "Sidebar promotion",
        "Author biography", "Reader comments", "Unrelated story", "unsafeScript",
    ):
        assert junk not in text


def test_single_and_nested_body_sections_are_not_duplicated():
    page = '<article><div class="post-content"><p>Opening.</p><div class="post-content">'
    page += f'<p>{END}</p></div></div></article>'
    text = ax._extract_site_specific_text(page, URL)
    assert "Opening." in text
    assert text.count(END) == 1


@pytest.mark.parametrize("url", [URL, "https://example.com/story", "https://arstechnica.com.evil.example/story"])
def test_missing_structure_and_other_hosts_fall_through(url):
    page = '<article><p>An ordinary article without Ars body markup.</p></article>'
    assert ax._extract_site_specific_text(page, url) == ""
    assert article_html._publisher_body_reconstruct(BeautifulSoup(page, "html.parser"), url) is None
    if url != URL:
        assert ax._extract_site_specific_text(PAGE, url) == ""
        assert article_html._publisher_body_reconstruct(BeautifulSoup(PAGE, "html.parser"), url) is None


@pytest.mark.parametrize("host,body", [
    ("theregister.com", '<div class="bodytext">{prose}<div class="articlesByTag">'
     '<p>Unrelated articles</p></div></div>'),
    ("macrumors.com", '<div class="js-content"><div class="ugc--hashed">{prose}</div></div>'),
    ("zdnet.com", '<div class="entry-content"><div class="zd-related-stories-flow">{prose}'
     '<div class="wp-block-ziff-davis-exco-video"><p>Video promotion</p></div></div>'
     '<div class="articleAuthorBioFooter-container"><p>Author biography</p></div>'
     '<div class="zd-post-footer-pattern"><p>Unrelated articles</p></div></div>'),
])
def test_publisher_body_keeps_prose_instead_of_navigation(host, body, monkeypatch):
    prose = f'<p>{LEAD}</p><h2>Details</h2><p>{END}</p>'
    page = '<html><body><article>' + body.format(prose=prose) + '</article>'
    page += '<aside><p>Unrelated articles</p></aside></body></html>'
    url = f"https://www.{host}/story/"
    # Reproduce a generic extraction that mistakes navigation for the body.
    monkeypatch.setattr(article_html, "_article_keep_text", lambda *_: "unrelated articles " * 100)
    monkeypatch.setattr(article_html, "_traf_body_html", lambda *_: "<p>Unrelated articles</p>")
    rich = article_html.clean_article_html(page, url)
    text = BeautifulSoup(rich, "html.parser").get_text(" ", strip=True)
    assert LEAD in text
    assert END in text
    assert "Unrelated articles" not in text
    assert "Author biography" not in text
    assert "Video promotion" not in text
    if host == "zdnet.com":
        classic = ax._extract_text_any(page, url)
        assert LEAD in classic
        assert END in classic
        assert "Unrelated articles" not in classic
