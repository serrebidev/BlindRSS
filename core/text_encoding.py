# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Byte-stream decoding with explicit user overrides and a strict detection chain (issue #75).

Both the feed fetcher and the full-text extractor decode raw HTTP bodies here so
that a per-feed encoding override (feed properties, F2) and the automatic
detection logic live in exactly one place.

Detection priority (when no override is given):
1. HTTP ``Content-Type`` header charset parameter.
2. Document self-declaration:
   - XML/feed bodies: the ``<?xml ... encoding="..."?>`` prolog;
   - HTML bodies: ``<meta charset="...">``, then the legacy
     ``<meta http-equiv="Content-Type" content="...; charset=...">``,
     scanned within the first 1024 bytes.
3. UTF-8 (with a BOM taking precedence when present).

Decoding never raises: a wrong or unknown encoding degrades to partial text via
``errors="replace"`` rather than crashing or showing binary garbage.
"""

from __future__ import annotations

import codecs
import re
from typing import Optional

# How far into the document self-declarations are searched. HTML5 requires the
# meta charset to appear within the first 1024 bytes; the XML prolog is at the
# very start anyway.
_META_SCAN_LIMIT = 1024

_CHARSET_IN_CONTENT_TYPE_RE = re.compile(rb"""charset\s*=\s*["']?\s*([A-Za-z0-9._:\-]+)""", re.I)
_CHARSET_IN_CONTENT_TYPE_STR_RE = re.compile(r"""charset\s*=\s*["']?\s*([A-Za-z0-9._:\-]+)""", re.I)
_XML_PROLOG_RE = re.compile(rb"""^\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._:\-]+)["']""", re.I)
_META_CHARSET_RE = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._:\-]+)""", re.I)
_META_HTTP_EQUIV_RE = re.compile(
    rb"""<meta[^>]+http-equiv\s*=\s*["']?content-type["']?[^>]*?content\s*=\s*["']([^"']+)["']""",
    re.I,
)

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)


def normalize_codec_name(name) -> Optional[str]:
    """Return the canonical Python codec name for ``name``, or None if unknown/empty.

    Case-insensitive; accepts the aliases Python's ``codecs`` module accepts
    (``utf-8``, ``UTF8``, ``windows-1251``, ``cp1251``, ``koi8-r``, ...).
    """
    raw = str(name or "").strip()
    if not raw:
        return None
    try:
        return codecs.lookup(raw).name
    except (LookupError, TypeError, ValueError):
        return None


def charset_from_content_type(content_type) -> Optional[str]:
    """Extract a valid charset from an HTTP Content-Type header value."""
    value = str(content_type or "")
    m = _CHARSET_IN_CONTENT_TYPE_STR_RE.search(value)
    if not m:
        return None
    return normalize_codec_name(m.group(1))


def _bom_encoding(data: bytes) -> Optional[str]:
    for bom, name in _BOMS:
        if data.startswith(bom):
            return name
    return None


def _declared_encoding(data: bytes, kind: str) -> Optional[str]:
    """Charset declared inside the document itself (XML prolog / HTML meta)."""
    head = data[:_META_SCAN_LIMIT]
    if kind == "xml":
        m = _XML_PROLOG_RE.match(head)
        if m:
            return normalize_codec_name(m.group(1).decode("ascii", "ignore"))
        return None
    # HTML: modern <meta charset=...> first, then the legacy http-equiv form.
    m = _META_CHARSET_RE.search(head)
    if m:
        # <meta http-equiv=... content="text/html; charset=x"> also matches the
        # charset= pattern, which is fine: both name the same charset source.
        found = normalize_codec_name(m.group(1).decode("ascii", "ignore"))
        if found:
            return found
    m = _META_HTTP_EQUIV_RE.search(head)
    if m:
        inner = _CHARSET_IN_CONTENT_TYPE_RE.search(m.group(1))
        if inner:
            return normalize_codec_name(inner.group(1).decode("ascii", "ignore"))
    return None


def detect_encoding(data: bytes, *, content_type: str = "", kind: str = "html") -> str:
    """Resolve the encoding for ``data`` using the automatic detection chain.

    ``kind`` is ``"xml"`` for feed documents (prolog declaration) or ``"html"``
    (meta tags). Always returns a valid codec name; falls back to utf-8.
    """
    bom = _bom_encoding(data)
    if bom:
        return bom
    header = charset_from_content_type(content_type)
    if header:
        return header
    declared = _declared_encoding(data, kind)
    if declared:
        return declared
    return "utf-8"


def decode_bytes(
    data,
    *,
    override: str = "",
    content_type: str = "",
    kind: str = "html",
) -> str:
    """Decode an HTTP body to text, honoring a user override first (issue #75).

    - ``override`` non-empty: decode with that codec, ``errors="replace"`` so a
      wrong user setting shows partial text instead of crashing. Unknown codec
      names fall through to automatic detection.
    - otherwise: BOM -> HTTP header charset -> document declaration -> utf-8.
      The auto-detected codec decodes strictly first; on failure the bytes are
      re-decoded with ``errors="replace"`` (after one latin-1 attempt when the
      chain ended at the utf-8 default, matching the historic feed behavior).
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if not isinstance(data, (bytes, bytearray)):
        return str(data)
    data = bytes(data)

    chosen = normalize_codec_name(override)
    if chosen:
        try:
            return data.decode(chosen, errors="replace")
        except Exception:
            return data.decode("utf-8", errors="replace")

    encoding = detect_encoding(data, content_type=content_type, kind=kind)
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        pass
    if encoding in ("utf-8", "utf-8-sig"):
        try:
            return data.decode("iso-8859-1")
        except Exception:
            pass
    return data.decode(encoding if normalize_codec_name(encoding) else "utf-8", errors="replace")
