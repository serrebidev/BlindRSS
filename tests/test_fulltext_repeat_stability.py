# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Regression: repeated extraction of the same article must not shrink.

trafilatura's ``deduplicate`` option counts paragraph sightings in a
process-global LRU shared by every extract call. With it enabled, extracting
the same article a few times (precision + recall passes, accessible-browser
prefetch + on-demand loads, plain revisits) made trafilatura drop the
article's own paragraphs as "duplicates": the first extractions returned the
full text, then later ones collapsed to a short stub. On macOS this presented
as "full text doesn't work" because the VoiceOver accessible browser
re-extracts aggressively. The extractor must therefore keep deduplicate off.
"""
from core import article_extractor


def _article_html():
    paras = [
        (
            f"Paragraph number {i} of the story body carries enough distinct words "
            "to clear trafilatura's minimum duplicate-check size, describing the "
            "events of the day in ordinary running prose that a news article "
            "would contain, sentence after sentence."
        )
        for i in range(8)
    ]
    body = "".join(f"<p>{p}</p>" for p in paras)
    return (
        "<html><head><title>Repeatable story</title></head><body>"
        f"<main><article><h1>Repeatable story</h1>{body}</article></main>"
        "</body></html>"
    )


def test_repeated_trafilatura_extraction_is_stable():
    # _trafilatura_extract_text specifically: when its result degrades, the
    # caller silently falls back to JSON-LD (often just a description) or the
    # crude soup text, which is what users saw as broken full text.
    html = _article_html()
    url = "https://example.com/news/repeatable-story"
    results = [
        article_extractor._trafilatura_extract_text(html, url) for _ in range(6)
    ]
    assert results[0], "extraction must produce text"
    assert len(results[0]) > 500, "extraction must capture the article body"
    for i, text in enumerate(results[1:], start=1):
        assert text == results[0], (
            f"pass {i} changed the extraction "
            f"({len(results[0])} chars -> {len(text)} chars); "
            "a process-global deduplication cache is eating repeated extractions"
        )


def test_repeated_full_pipeline_extraction_is_stable():
    html = _article_html()
    url = "https://example.com/news/repeatable-story"
    results = [article_extractor._extract_text_any(html, url) for _ in range(6)]
    assert results[0]
    assert all(text == results[0] for text in results[1:])
