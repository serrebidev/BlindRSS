# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Issue #75: per-feed encoding overrides and the automatic detection chain.

Covers core.text_encoding (the shared decode helper), the feed refresh decode
path, and the full-text extractor's page decode.
"""

import types

import core.article_extractor as article_extractor
import core.utils as utils
from core import text_encoding

import providers.local as local_provider


RU_TEXT = "Это статья о погоде в Москве"


def _resp(status_code, content: bytes, content_type: str = "text/html"):
    return types.SimpleNamespace(
        status_code=status_code,
        content=content,
        text=content.decode("latin-1"),  # mimics requests' charset-less default
        encoding=None,
        headers={"Content-Type": content_type},
        url="https://example.com/x",
    )


# --- normalize_codec_name -------------------------------------------------

def test_codec_names_are_case_insensitive_and_alias_tolerant():
    assert text_encoding.normalize_codec_name("UTF-8") == "utf-8"
    assert text_encoding.normalize_codec_name("cp1251") == "cp1251"
    assert text_encoding.normalize_codec_name("Windows-1251") == "cp1251"
    assert text_encoding.normalize_codec_name("KOI8-R") == "koi8-r"
    assert text_encoding.normalize_codec_name("") is None
    assert text_encoding.normalize_codec_name("no-such-codec") is None


# --- detection chain ------------------------------------------------------

def test_override_beats_everything():
    data = RU_TEXT.encode("cp1251")
    # Header and meta both lie (say utf-8); the user override must win.
    html = b'<html><head><meta charset="utf-8"></head><body>' + data + b"</body></html>"
    out = text_encoding.decode_bytes(html, override="windows-1251", content_type="text/html; charset=utf-8")
    assert RU_TEXT in out


def test_http_header_charset_wins_over_meta():
    body = b'<html><head><meta charset="utf-8"></head><body>' + RU_TEXT.encode("cp1251") + b"</body></html>"
    out = text_encoding.decode_bytes(body, content_type="text/html; charset=windows-1251")
    assert RU_TEXT in out


def test_modern_meta_charset_detected():
    body = b'<html><head><meta charset="windows-1251"></head><body>' + RU_TEXT.encode("cp1251") + b"</body></html>"
    assert RU_TEXT in text_encoding.decode_bytes(body)


def test_legacy_http_equiv_meta_detected():
    body = (
        b'<html><head><meta http-equiv="Content-Type" content="text/html; charset=koi8-r"></head><body>'
        + RU_TEXT.encode("koi8-r")
        + b"</body></html>"
    )
    assert RU_TEXT in text_encoding.decode_bytes(body)


def test_xml_prolog_encoding_detected():
    xml = ('<?xml version="1.0" encoding="windows-1251"?><rss><channel><title>'
           + RU_TEXT + "</title></channel></rss>").encode("cp1251")
    assert RU_TEXT in text_encoding.decode_bytes(xml, kind="xml")


def test_utf8_default_when_nothing_declared():
    assert RU_TEXT in text_encoding.decode_bytes(RU_TEXT.encode("utf-8"))


def test_utf8_bom_wins():
    data = b"\xef\xbb\xbf" + RU_TEXT.encode("utf-8")
    out = text_encoding.decode_bytes(data, content_type="text/html; charset=windows-1251")
    assert RU_TEXT in out and "﻿" not in out


def test_bad_override_never_raises():
    data = RU_TEXT.encode("cp1251")
    # utf-8 override over cp1251 bytes: partial text with replacement chars, no crash.
    out = text_encoding.decode_bytes(data, override="utf-8")
    assert isinstance(out, str) and out
    # Unknown codec name falls through to auto detection instead of crashing.
    out2 = text_encoding.decode_bytes(RU_TEXT.encode("utf-8"), override="not-a-codec")
    assert RU_TEXT in out2


def test_meta_outside_first_1024_bytes_is_ignored():
    body = b"<html><head>" + b" " * 1200 + b'<meta charset="koi8-r"></head><body>x</body></html>'
    assert text_encoding.detect_encoding(body, kind="html") == "utf-8"


# --- feed decode path -----------------------------------------------------

def test_decode_feed_text_uses_xml_prolog():
    xml = ('<?xml version="1.0" encoding="windows-1251"?><rss><channel><title>'
           + RU_TEXT + "</title></channel></rss>").encode("cp1251")
    assert RU_TEXT in local_provider._decode_feed_text(xml)


def test_parse_feed_document_with_override_decoded_text():
    raw = ('<?xml version="1.0"?><rss version="2.0"><channel><title>' + RU_TEXT +
           "</title><item><title>" + RU_TEXT + "</title><link>https://e.com/1</link></item>"
           "</channel></rss>").encode("cp1251")
    decoded = text_encoding.decode_bytes(raw, override="windows-1251", kind="xml")
    parsed = local_provider._parse_feed_document(decoded, decoded, "application/rss+xml")
    assert parsed.entries and parsed.entries[0]["title"] == RU_TEXT


# --- full-text extractor path ---------------------------------------------

_CP1251_PAGE = ("<html><head><title>t</title></head><body><article><p>"
                + (RU_TEXT + ". ") * 40 + "</p></article></body></html>").encode("cp1251")


def test_fetch_page_override_decodes_cp1251(monkeypatch):
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, _CP1251_PAGE))
    res = article_extractor._fetch_page("https://example.com/x", encoding_override="windows-1251")
    assert res.html and RU_TEXT in res.html


def test_fetch_page_auto_uses_meta_charset(monkeypatch):
    page = (b'<html><head><meta charset="windows-1251"><title>t</title></head><body><article><p>'
            + ((RU_TEXT + ". ") * 40).encode("cp1251") + b"</p></article></body></html>")
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, page))
    res = article_extractor._fetch_page("https://example.com/x")
    assert res.html and RU_TEXT in res.html


def test_fetch_page_auto_defaults_to_utf8_without_hints(monkeypatch):
    page = ("<html><head><title>t</title></head><body><article><p>"
            + (RU_TEXT + ". ") * 40 + "</p></article></body></html>").encode("utf-8")
    monkeypatch.setattr(utils, "safe_requests_get", lambda url, **kw: _resp(200, page))
    res = article_extractor._fetch_page("https://example.com/x")
    assert res.html and RU_TEXT in res.html


def test_render_full_article_forwards_encoding(monkeypatch):
    seen = {}

    def fake_extract(url, max_pages=6, timeout=20, metadata_sink=None, encoding=""):
        seen["encoding"] = encoding
        return article_extractor.FullArticle(url=url, title="T", author="A", text="Body " * 60)

    monkeypatch.setattr(article_extractor, "extract_full_article", fake_extract)
    out = article_extractor.render_full_article(
        "https://example.com/x", prefer_feed_content=False, encoding="windows-1251"
    )
    assert out and seen["encoding"] == "windows-1251"


def test_render_full_article_without_encoding_omits_kwarg(monkeypatch):
    # Test doubles without the new kwarg must keep working when no override is set.
    def fake_extract(url, max_pages=6, timeout=20):
        return article_extractor.FullArticle(url=url, title="T", author="A", text="Body " * 60)

    monkeypatch.setattr(article_extractor, "extract_full_article", fake_extract)
    out = article_extractor.render_full_article("https://example.com/x", prefer_feed_content=False)
    assert out and "Body" in out
