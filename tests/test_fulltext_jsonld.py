import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import article_extractor


class _FakeTrafilatura:
    def __init__(self, precision_text: str, recall_text: str) -> None:
        self.precision_text = precision_text
        self.recall_text = recall_text
        self.calls = []

    def extract(self, _html: str, url=None, **kwargs):  # noqa: ARG002
        self.calls.append({"url": url, **kwargs})
        if kwargs.get("favor_precision"):
            return self.precision_text
        if kwargs.get("favor_recall"):
            return self.recall_text
        return ""


def test_json_ld_used_when_trafilatura_empty(monkeypatch):
    json_body = ("JSON-LD full text " * 20).strip()
    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body><article><p>fallback</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text="short", recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://example.com/x")
    assert json_body[:40] in out


def test_json_ld_preferred_when_longer_than_trafilatura(monkeypatch):
    precision_text = ("precision " * 25).strip()  # ~225 chars
    json_body = ("json-body " * 50).strip()  # significantly longer
    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "Article", "articleBody": "{json_body}"}}
      </script>
    </head><body><article><p>fallback</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_text, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://example.com/x")
    assert out.startswith("json-body")


def test_trafilatura_lede_kept_when_json_ld_omits_it(monkeypatch):
    # Wired/Conde Nast: when the lede uses styled lead-in markup, the CMS omits that
    # entire first paragraph from JSON-LD articleBody. The JSON-LD text is still
    # substantial (>1000 chars, the old short-circuit threshold) but starts at
    # paragraph 2, while trafilatura extracts the full article including the lede.
    lede = (
        "The European Space Agency released a satellite image that shows the upheaval "
        "left behind by the pair of earthquakes that rocked the region last week."
    )
    rest = " ".join(
        f"Body paragraph {i} with enough words to read like a real article sentence."
        for i in range(1, 21)
    )
    precision_text = lede + "\n" + rest

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{rest}"}}
      </script>
    </head><body><article><p>{lede}</p><p>{rest}</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_text, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://www.wired.com/story/x/")
    assert len(rest) > 1000
    assert out.startswith(lede)
    assert rest[:40] in out


def test_json_ld_winner_gets_missing_lede_prepended(monkeypatch):
    # Even when JSON-LD legitimately wins the length comparison (trafilatura only got a
    # fragment), a lede that only trafilatura captured must be re-attached in front.
    lede = (
        "Writing about artificial intelligence each week means the lede paragraph "
        "sometimes exists only in the rendered page markup."
    )
    shared = (
        "A group of researchers has set up a crowdsourced website where the public "
        "can file reports about artificially intelligent systems behaving badly."
    )
    json_body = shared + " " + ("Additional reporting that only JSON-LD retained. " * 30).strip()
    precision_text = lede + "\n" + shared

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body><article><p>{lede}</p><p>{shared}</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_text, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://www.wired.com/story/y/")
    assert len(json_body) > len(precision_text) * 1.1
    assert out.startswith(lede)
    assert "Additional reporting that only JSON-LD retained." in out


def test_json_ld_winner_gets_two_missing_lede_paragraphs_prepended(monkeypatch):
    lede_one = (
        "The first rendered lead paragraph explains why readers should care about "
        "the investigation before the structured article body begins."
    )
    lede_two = (
        "The second rendered lead paragraph adds context that the page shows above "
        "the body copy but the JSON-LD articleBody skipped."
    )
    shared = (
        "The body begins here with the first paragraph that appears in both the "
        "page extraction and the JSON-LD article body."
    )
    json_body = shared + " " + ("Structured data retained a much longer tail. " * 30).strip()
    precision_text = "\n".join([lede_one, lede_two, shared])

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body>
      <article><p>{lede_one}</p><p>{lede_two}</p><p>{shared}</p></article>
    </body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_text, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://www.wired.com/story/z/")
    assert len(json_body) > len(precision_text) * 1.1
    assert out.startswith(lede_one + "\n\n" + lede_two)
    assert shared in out
    assert "Structured data retained a much longer tail." in out


def test_json_ld_winner_does_not_prepend_unaligned_preamble(monkeypatch):
    preamble = (
        "This unrelated page preamble is plausible article text but it never lines "
        "up with the beginning of the structured article body."
    )
    unrelated = (
        "Another introductory paragraph describes a different promotion and should "
        "not be guessed into the final extracted article."
    )
    shared = (
        "The structured article body starts with the actual article paragraph that "
        "should remain first in the extracted text."
    )
    json_body = shared + " " + ("Structured data includes the complete article body. " * 30).strip()
    precision_text = "\n".join([preamble, unrelated])

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body><article><p>{shared}</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_text, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://example.com/story/")
    assert len(json_body) > len(precision_text) * 1.1
    assert out.startswith(shared)
    assert preamble not in out
    assert unrelated not in out


def test_json_ld_fallback_gets_missing_lede_from_html_when_trafilatura_empty(monkeypatch):
    lede = (
        "The visible page starts with a lead paragraph that the structured data "
        "does not include."
    )
    shared = (
        "The structured article body starts with a linked phrase, which also appears "
        "in the rendered page."
    )
    json_body = shared + " " + ("JSON-LD still has the rest of the article. " * 25).strip()

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body>
      <article>
        <p>{lede}</p>
        <p>The structured article body starts with a <a href="/x">linked phrase</a>, which also appears in the rendered page.</p>
      </article>
    </body></html>
    """

    fake = _FakeTrafilatura(precision_text="", recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://www.wired.com/story/html-fallback/")
    assert out.startswith(lede)
    assert shared in out
    assert "JSON-LD still has the rest of the article." in out


def test_json_ld_fallback_does_not_prepend_unaligned_html_preamble(monkeypatch):
    preamble = (
        "This visible paragraph is not part of the JSON-LD article and never aligns "
        "with its first body paragraph."
    )
    shared = (
        "The actual structured article starts here and should remain the first "
        "paragraph in the fallback output."
    )
    json_body = shared + " " + ("JSON-LD has enough complete body text. " * 25).strip()

    html = f"""
    <html><head>
      <script type="application/ld+json">
        {{"@type": "NewsArticle", "articleBody": "{json_body}"}}
      </script>
    </head><body><article><p>{preamble}</p><p>Detached sidebar copy.</p></article></body></html>
    """

    fake = _FakeTrafilatura(precision_text="", recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._extract_text_any(html, url="https://example.com/story/html-fallback/")
    assert out.startswith(shared)
    assert preamble not in out
