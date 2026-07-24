# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

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


def test_fulltext_lead_recovery_runs_only_on_allowlisted_domains(monkeypatch):
    meta_desc = "Meta intro sentence. More words to exceed forty characters for sure."
    precision_body = ("Body sentence. " * 30).strip()  # ensure > 200 chars

    html = f"""
    <html><head>
      <meta name="description" content="{meta_desc}">
      <meta property="og:title" content="Some title - Wirtualne Media">
      <title>Some title - Wirtualne Media</title>
    </head><body><article><p>ignored</p></article></body></html>
    """

    recall_text = "\n".join(["Some title", meta_desc, precision_body])
    fake = _FakeTrafilatura(precision_text=precision_body, recall_text=recall_text)

    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out_allowed = article_extractor._trafilatura_extract_text(html, url="https://www.wirtualnemedia.pl/x")
    assert out_allowed.startswith(meta_desc)
    assert precision_body in out_allowed
    assert len(fake.calls) == 2  # precision + recall

    fake.calls.clear()
    out_denied = article_extractor._trafilatura_extract_text(html, url="https://example.com/x")
    assert out_denied == precision_body
    assert len(fake.calls) == 1  # precision only; recall not attempted


def test_fulltext_lead_recovery_falls_back_to_meta_description_when_recall_misses(monkeypatch):
    meta_desc = "Meta intro sentence. More words to exceed forty characters for sure."
    precision_body = ("Body sentence. " * 30).strip()  # ensure > 200 chars

    html = f"""
    <html><head>
      <meta name="description" content="{meta_desc}">
      <meta property="og:title" content="Some title - Wirtualne Media">
      <title>Some title - Wirtualne Media</title>
    </head><body><article><p>ignored</p></article></body></html>
    """

    # Recall mode doesn't include the meta description, so lead recovery should fall back to
    # prepending the meta description itself (allowlist-only).
    recall_text = precision_body
    fake = _FakeTrafilatura(precision_text=precision_body, recall_text=recall_text)

    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._trafilatura_extract_text(html, url="https://www.wirtualnemedia.pl/x")
    assert out.startswith(meta_desc)
    assert precision_body in out
    assert len(fake.calls) == 2  # precision + recall


def test_fulltext_lead_recovery_uses_site_lead_html_when_available(monkeypatch):
    lead_text = (
        'Indyjskie ministerstwo IT wydało nakaz firmie X należącej do Elona Muska podjęcia działań '
        'naprawczych wobec Groka. Chodzi między innymi o ograniczenie generowania treści zawierających '
        '"nagość, seksualizację, treści o charakterze seksualnym lub w inny sposób niezgodne z prawem".'
    )
    meta_desc = lead_text[:180] + "..."
    precision_body = ("Body sentence. " * 30).strip()  # ensure > 200 chars

    html = f"""
    <html><head>
      <meta name="description" content="{meta_desc}">
      <meta property="og:title" content="Some title - Wirtualne Media">
      <title>Some title - Wirtualne Media</title>
    </head><body>
      <article>
        <div class="wm-article-header-lead"><p>{lead_text}</p></div>
      </article>
    </body></html>
    """

    fake = _FakeTrafilatura(precision_text=precision_body, recall_text="")
    monkeypatch.setattr(article_extractor, "trafilatura", fake)

    out = article_extractor._trafilatura_extract_text(html, url="https://www.wirtualnemedia.pl/x")
    assert out.startswith(lead_text)
    assert precision_body in out
    assert len(fake.calls) == 1  # precision only; no need for recall
