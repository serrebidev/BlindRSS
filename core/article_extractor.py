# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""
Full-text article extraction using trafilatura.

Goal:
- Given an article URL, extract clean text (no ads/boilerplate) plus title and author.
- Follow simple multi-page pagination (rel=next / next links) and merge text.
- Provide safe fallbacks for feed items without a webpage URL (e.g., podcast episodes).
"""

from __future__ import annotations

import html
import json
import re
import time
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Tuple, List, Set
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from core import utils
from core import text_encoding

# User-facing extraction failures are translated (PR #69). Every _() call here
# MUST run at raise time, never at module import: this module is pulled in via
# gui.mainframe from main.py's import block, which runs BEFORE main.py calls
# i18n.setup(). A module-level `MSG = _("...")` therefore captures the English
# NullTranslations fallback permanently, and no catalog can replace it later --
# that is exactly why the messages looked untranslated. Message constants are
# functions for this reason; do not "simplify" them back into constants.
from core.i18n import _

LOG = logging.getLogger(__name__)

try:
    import trafilatura
    from trafilatura.metadata import extract_metadata
except Exception:
    trafilatura = None
    extract_metadata = None


class ExtractionError(RuntimeError):
    """Raised when an extraction attempt fails in a way worth surfacing to the UI."""
    pass


@dataclass
class FullArticle:
    url: str
    title: str
    author: str
    text: str
    html: str = ""


_MEDIA_EXTS = (
    ".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus",
    ".mp4", ".mkv", ".webm", ".mov", ".m4v", ".avi",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg",
    ".pdf",
)

_LEAD_RECOVERY_ALLOWED_NETLOC_SUFFIXES = {
    # Some sites have a meaningful lead/intro in the HTML meta description that trafilatura may
    # skip when running in precision mode.
    "wirtualnemedia.pl",
}

_LEAD_RECOVERY_MIN_PRECISION_LEN = 200
_LEAD_RECOVERY_MIN_DESC_LEN = 60
_LEAD_RECOVERY_DESC_SNIPPET_LEN = 120
_LEAD_RECOVERY_DESC_HIT_SNIPPET_LEN = 80
_LEAD_RECOVERY_MAX_RECALL_NORM_CHARS = 8000
_LEAD_RECOVERY_MAX_SCAN_PARAS = 8
_LEAD_RECOVERY_MIN_PARA_LEN = 40
_LEAD_RECOVERY_MAX_PARA_LEN = 800
_LEAD_RECOVERY_MIN_PUNCT_PARA_LEN = 120
_LEAD_RECOVERY_MAX_INTRO_PARAS = 2

_TITLE_SUFFIX_STRIP_SEPARATORS = (" | ", " — ", " – ")
_META_DESCRIPTION_TAG_ATTRS: List[dict] = [
    {"property": "og:description"},
    {"name": "description"},
    {"name": "twitter:description"},
]
_META_TITLE_TAG_ATTRS: List[dict] = [
    {"property": "og:title"},
    {"name": "twitter:title"},
    {"name": "title"},
]

_JSON_LD_TEXT_FIELDS = ("articleBody", "text")
_JSON_LD_MIN_TEXT_LEN = 120
_BLOOMBERG_VIDEO_DESCRIPTION_MIN_LEN = 80

# Axios (Next.js) ships the canonical article body inside the __NEXT_DATA__ JSON blob
# (props.pageProps.data.story.bodyHtml). Some page variants render no body in the DOM at all,
# so DOM-based extraction only finds related-story cards and the "preferred source on Google"
# promo. The JSON body is present in every variant, so it is the reliable source.
_AXIOS_STORY_MIN_TEXT_LEN = 200
_AXIOS_BODY_HTML_KEYS = ("beforeKeepReading", "afterKeepReading")

# Anti-bot / human-verification interstitials.
#
# These are NOT articles: they are access-control gates (Cloudflare challenges, "you're not a
# robot" / "unusual activity" pages from Bloomberg/Akamai/PerimeterX/DataDome, etc.). We must not
# store the gate text as article content. When we detect one, extraction is treated as a failure so
# the UI degrades cleanly to the feed snippet plus the original link.
#
# We do not attempt to defeat these gates. Detection only exists to fail gracefully.
_BOT_INTERSTITIAL_MARKERS = (
    # Cloudflare challenge / managed challenge pages
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "__cf_chl_",
    "cf_chl_opt",
    "enable javascript and cookies to continue",
    "ddos protection by cloudflare",
    "performance & security by cloudflare",
    # Generic "are you a human/robot" gates (Bloomberg, Reuters, Akamai, PerimeterX, DataDome, ...)
    "we've detected unusual activity from your computer network",
    "let us know you're not a robot",
    "please verify you are a human",
    "verify you are human",
    "press & hold to confirm you",
    "please make sure your browser supports javascript and cookies",
    "block reference id",
    "why have i been blocked",
    "access to this page has been denied",
    "please complete the security check to access",
    "pardon our interruption",
    "as you were browsing, something about your browser made us think you were a bot",
    # Vercel / generic WAF verification page (seen on Neowin, also relayed through read-proxies
    # as markdown: "## Performing security verification ...")
    "performing security verification",
    "uses a security service to protect against malicious bots",
    "while the website verifies you are not a bot",
    # DataDome (nytimes.com and others). Its block document carries no human-readable
    # sentence beyond "Please enable JS and disable any ad blocker" — the reliable
    # signals are its CAPTCHA host and the `dd` config object it ships.
    "geo.captcha-delivery.com",
    "ct.captcha-delivery.com",
    "please enable js and disable any ad blocker",
)

# Block-page bodies are short; a long article that merely mentions one of these phrases should not be
# discarded. Only treat a post-extraction body as a gate when it is small.
_BOT_INTERSTITIAL_MAX_BODY_LEN = 1500

def _has_stored_clearance(url: str) -> bool:
    """True when the cookie jar holds a bot-check clearance for this URL's site."""
    try:
        from core import site_cookies

        return site_cookies.has_clearance_for(url)
    except Exception:
        return False


def _readable_browser_names() -> list:
    """Browsers whose cookies BlindRSS can read by itself, newest session first."""
    try:
        from core import site_cookies

        seen = []
        for profile in site_cookies.list_browser_profiles():
            name = str(profile.get("browser", "") or "")
            if name and name not in seen:
                seen.append(name)
        return seen
    except Exception:
        return []


def _blocked_interstitial_message(url: str = "") -> str:
    # When the site is one we can regain access to, say how. The generic
    # "open it in your browser" is a dead end for a challenge site: visiting it
    # in a browser BlindRSS can read is what actually restores the full text,
    # because the clearance those checks issue lasts well under an hour and the
    # app picks a fresh one up on its own.
    browsers = _readable_browser_names() if url else []
    if browsers and _has_stored_clearance(url):
        return _(
            "This page is behind an anti-bot / human-verification check, and the access "
            "BlindRSS had for this site has expired — these checks only stay valid for a short "
            "time. Open the page in {browser} and BlindRSS will pick the access back up "
            "automatically within a minute."
        ).format(browser=browsers[0])
    return _(
        "This page is behind an anti-bot / human-verification check "
        "(e.g. Cloudflare or a \"you're not a robot\" page), so the full text can't be fetched "
        "automatically. Open the original link in your browser to read it."
    )

# Video-only and index pages have no article body, so extraction returns the page's navigation
# and related-story headlines instead (e.g. local-TV video pages reached via Google News). Such
# text is a stack of short, punctuation-free link captions; real articles are sentences. Only
# small bodies are checked so a long article containing a headline list is never discarded.
_LINK_LIST_MAX_BODY_LEN = 1500
_LINK_LIST_MIN_LINES = 4
_LINK_LIST_MAX_LINE_LEN = 90
_LINK_LIST_MIN_FRACTION = 0.6
# Counting lines alone rejects real articles built from many short segment titles with a few
# real paragraphs between them — e.g. NPR program pages ("Wait Wait...Don't Tell Me!"), whose
# rundown is a stack of bold segment names interleaved with prose blurbs. Those pages are 70%+
# link-like *by line*, but only ~35% by character mass, while a true navigation stack is ~90%
# by both. Requiring both fractions keeps the junk out without discarding short real articles.
_LINK_LIST_MIN_CHAR_FRACTION = 0.6
_LINK_LIST_SENTENCE_END_RE = re.compile(r"[.!?…](\s|$)")
# The "#3 Reply by alice — 2026-07-19 13:54:46" line _extract_forum_thread_text
# writes before each post. Short and punctuation-free by design, so it must not
# be counted as evidence that a thread is a navigation link list.
_FORUM_POST_HEADER_LINE_RE = re.compile(r"^#\d+\s+\S")

def _link_list_only_message() -> str:
    return _(
        "The page has no readable article text — only navigation or related-story links were "
        "found (common for video-only pages). Open the original link in your browser to view it."
    )


def _looks_like_bot_interstitial(content: str) -> bool:
    """Return True if `content` (HTML or already-extracted text) is an anti-bot/verification gate."""
    if not content:
        return False
    low = content.replace("’", "'").lower()
    # Google News' redirect endpoint can hand a non-consenting client Google's generic consent
    # document instead of the publisher URL.  This is not article content; keep it out of the
    # reader just like a WAF page.  Require both phrases so an article merely discussing one of
    # them is never misclassified.
    if "before you continue to google" in low and "we use cookies and data" in low:
        return True
    if len(low) < 2000 and "powered and protected by" in low and "akamai" in low:
        return True
    return any(marker in low for marker in _BOT_INTERSTITIAL_MARKERS)


def _looks_like_link_list(text: str) -> bool:
    """Return True if short extracted `text` is mostly navigation/headline-like link captions."""
    if not text or len(text) > _LINK_LIST_MAX_BODY_LEN:
        return False
    # Structure marker lines (tables, headings, list items, quotes) and forum
    # post headers are intentional short lines, not navigation captions; a short
    # article that is mostly a real list must not be rejected as a link list, and
    # a one-post thread of "here are the links" must not be rejected either
    # because the header we added counts against it.
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
        and not _is_marker_line(line.strip())
        and not _FORUM_POST_HEADER_LINE_RE.match(line.strip())
    ]
    if len(lines) < _LINK_LIST_MIN_LINES:
        return False
    linky_lines = [
        line
        for line in lines
        if len(line) <= _LINK_LIST_MAX_LINE_LEN and not _LINK_LIST_SENTENCE_END_RE.search(line)
    ]
    if len(linky_lines) / len(lines) < _LINK_LIST_MIN_FRACTION:
        return False
    # Weigh the same test by text mass: a navigation stack is nearly all link captions, whereas
    # a real article's prose paragraphs carry most of its characters even when they are
    # outnumbered by short lines.
    total_chars = sum(len(line) for line in lines)
    if not total_chars:
        return False
    linky_chars = sum(len(line) for line in linky_lines)
    return linky_chars / total_chars >= _LINK_LIST_MIN_CHAR_FRACTION


# A hard paywall (e.g. The Information) server-renders only the headline, byline, and a
# "Subscribe to unlock" call-to-action; the body is injected client-side after login and is
# absent from the HTML we fetch. Generic extraction then "succeeds" with that tiny stub, which
# would be shown (and read aloud) as if it were the article. Detecting it lets the caller fall
# back to feed content — which, for a subscriber's full-text feed, is the whole story.
_PAYWALL_STUB_MAX_LEN = 600
_PAYWALL_CTA_RE = re.compile(
    r"(?i)\b("
    r"subscribe to (?:unlock|read|continue|view)"
    r"|subscribe (?:now |today )?(?:for|to get) (?:full |unlimited )?access"
    r"|to (?:continue|keep) reading[, ]"
    r"|this (?:article|story|content) is (?:for|exclusive to|available to) (?:subscribers|members)"
    r"|(?:sign in|log ?in) to (?:read|continue|unlock)"
    r"|become a (?:subscriber|member) to"
    r"|unlock this (?:article|story)"
    r")"
)

def _paywall_message() -> str:
    return _(
        "This article is behind a paywall (subscription required), so the full text can't be "
        "fetched automatically. Open the original link in your browser to read it."
    )


def _looks_like_paywall_stub(text: str) -> bool:
    """Return True if `text` is a short subscribe-to-read paywall stub, not an article."""
    if not text:
        return False
    if len(text) > _PAYWALL_STUB_MAX_LEN:
        return False
    return bool(_PAYWALL_CTA_RE.search(text))


# Metered publishers (nytimes.com) sometimes serve only the first few paragraphs and end
# the article body with a role="note" subscribe line; other times the same URL renders in
# full. Extraction then "succeeds" with a story that just stops mid-report, because the
# note explaining why is stripped as chrome by both readers. Match that cut-off note so
# the truncation is stated instead of trailing off.
#
# Do NOT key on NYT's `data-paywall-inert` attribute: it is present on the full render
# too, so it would label complete articles as previews (verified live 2026-07-20).
_METERED_PREVIEW_MARKERS = ("to read as many articles as you like",)


def _looks_like_metered_preview(html_text: str) -> bool:
    """Return True if `html_text` is a metered free preview rather than the whole article."""
    if not html_text:
        return False
    low = html_text[:400000].lower()
    return any(marker in low for marker in _METERED_PREVIEW_MARKERS)


def metered_preview_notice() -> str:
    return _(
        "Only the free preview of this article is published on the page — the rest "
        "requires a subscription. Open the original link in your browser to read it."
    )


def _lead_recovery_enabled(url: str) -> bool:
    if not url:
        return False
    try:
        host = urlsplit(url).hostname
    except (AttributeError, TypeError, ValueError):
        return False
    if not host or not isinstance(host, str):
        return False
    host = host.lower()
    return any(host == d or host.endswith("." + d) for d in _LEAD_RECOVERY_ALLOWED_NETLOC_SUFFIXES)


def _looks_like_media_url(url: str) -> bool:
    try:
        path = (urlsplit(url).path or "").lower()
        return any(path.endswith(ext) for ext in _MEDIA_EXTS)
    except Exception:
        return False


def _looks_like_id3_media_url(url: str) -> bool:
    """True for MP3 paths whose leading ID3 tag can contain readable notes."""
    try:
        return (urlsplit(url).path or "").lower().endswith(".mp3")
    except Exception:
        return False


def is_extractable_fulltext_url(url: str) -> bool:
    """Whether a URL can yield webpage text or bounded embedded media text."""
    value = str(url or "").strip()
    return bool(value) and (
        not _looks_like_media_url(value) or _looks_like_id3_media_url(value)
    )


def _normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\u200b", "").replace("\u2060", "").replace("\ufeff", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_paragraphs(text: str) -> List[str]:
    t = _normalize_whitespace(text or "")
    if not t:
        return []
    # Split by blank lines first (strong paragraph separator), then by single newlines.
    # This handles mixed separators like "p1\\np2\\n\\np3" without merging p1+p2.
    blocks = re.split(r"\n\s*\n", t)
    return [p.strip() for block in blocks for p in block.split("\n") if p.strip()]


def _normalize_for_match(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def _strip_trailing_ellipsis(text: str) -> str:
    return re.sub(r"(?:\.\.\.|…)\s*$", "", (text or "").strip()).strip()


def _is_reasonable_lead_paragraph(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if len(t) < _LEAD_RECOVERY_MIN_PARA_LEN or len(t) > _LEAD_RECOVERY_MAX_PARA_LEN:
        return False
    if re.search(r"[.!?]", t):
        return True
    return len(t) >= _LEAD_RECOVERY_MIN_PUNCT_PARA_LEN


def _strip_title_suffix(title: str) -> str:
    t = (title or "").strip()
    for sep in _TITLE_SUFFIX_STRIP_SEPARATORS:
        if sep in t:
            # Split from the right and take the longest segment.
            # This tends to drop short site-name suffix/prefix; we intentionally avoid stripping " - "
            # because it's common in legitimate titles.
            return max(t.rsplit(sep, 1), key=len).strip()
    return t


# Byline meta tags, checked only when trafilatura found no author. `byl` is NYT's
# (value already reads "By Simon Romero"), the rest are the common conventions.
_AUTHOR_META_CANDIDATES = [
    {"name": "byl"},
    {"name": "author"},
    {"property": "article:author"},
    {"name": "parsely-author"},
    {"name": "sailthru.author"},
]
_AUTHOR_BY_PREFIX_RE = re.compile(r"(?i)^\s*by[\s:]+")


def _extract_meta_content(soup: BeautifulSoup, candidates: List[dict]) -> str:
    for attrs in candidates:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            content = (tag.get("content") or "").strip()
            if content:
                return content
    return ""


def _parse_html_soup(html: Optional[str], *, context: str) -> Optional[BeautifulSoup]:
    if not html:
        return None
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        LOG.debug("Failed to parse HTML for %s", context, exc_info=True)
        return None


def _extract_meta_description(*, html: Optional[str] = None, soup: Optional[BeautifulSoup] = None) -> str:
    if soup is None:
        soup = _parse_html_soup(html, context="meta description")
        if soup is None:
            return ""

    return _extract_meta_content(
        soup,
        _META_DESCRIPTION_TAG_ATTRS,
    )


def _extract_page_title(*, html: Optional[str] = None, soup: Optional[BeautifulSoup] = None) -> str:
    if soup is None:
        soup = _parse_html_soup(html, context="page title")
        if soup is None:
            return ""

    meta_title = _extract_meta_content(
        soup,
        _META_TITLE_TAG_ATTRS,
    )
    if meta_title:
        return meta_title
    t = soup.find("title")
    if t and t.get_text(strip=True):
        return t.get_text(strip=True)
    return ""


def _collect_json_ld_text(obj, out: List[str]) -> None:
    if isinstance(obj, dict):
        for key in _JSON_LD_TEXT_FIELDS:
            val = obj.get(key)
            if isinstance(val, str):
                out.append(val)
            elif isinstance(val, list):
                joined = " ".join(v for v in val if isinstance(v, str))
                if joined:
                    out.append(joined)
        for v in obj.values():
            _collect_json_ld_text(v, out)
        return
    if isinstance(obj, list):
        for v in obj:
            _collect_json_ld_text(v, out)


def _jsonld_types(obj) -> Set[str]:
    raw = obj.get("@type") if isinstance(obj, dict) else None
    values = raw if isinstance(raw, list) else [raw]
    return {str(v or "").strip().lower() for v in values if str(v or "").strip()}


def _collect_bloomberg_video_descriptions(obj, out: List[str]) -> None:
    if isinstance(obj, dict):
        if "videoobject" in _jsonld_types(obj):
            for key in ("description", "transcript", "caption"):
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    out.append(val)
        for v in obj.values():
            _collect_bloomberg_video_descriptions(v, out)
        return
    if isinstance(obj, list):
        for v in obj:
            _collect_bloomberg_video_descriptions(v, out)


def _extract_json_ld_text(html_text: str) -> str:
    # Parameter is `html_text`, not `html`: the body below needs the stdlib ``html`` module
    # for entity unescaping, and a parameter named `html` would shadow it.
    if not html_text:
        return ""
    soup = _parse_html_soup(html_text, context="json-ld")
    if soup is None:
        return ""

    candidates: List[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _collect_json_ld_text(data, candidates)

    if not candidates:
        return ""

    cleaned: List[str] = []
    for c in candidates:
        first_tag = re.search(r"<[a-z][^>]*>", c, flags=re.I)
        if first_tag:
            # Some publishers (notably Sky News) put the standfirst directly before the first
            # ``<p>`` in articleBody.  Preserve that leading text while stripping the markup.
            prefix = html.unescape(_normalize_whitespace(c[: first_tag.start()]))
            fragment_text = _html_fragment_to_text(c[first_tag.start() :])
            c = "\n\n".join(part for part in (prefix, fragment_text) if part)
        else:
            # No markup survives, so the branch above (which unescapes as a side effect of
            # parsing) never runs. The value is still HTML-derived though: publishers whose CMS
            # tag-strips articleBody leave entities encoded, so a shell command in the story
            # reads out as "sudo mkdir -p ... &amp;&amp; sudo defaults write" (mashable.com).
            c = html.unescape(c)
        # A naive tag-stripper drops the <script> ELEMENT but keeps its source as text, so the
        # page's JavaScript trails the last paragraph. Remove it before the length comparison
        # below, or the junk can win the "longest candidate" vote on its own bulk.
        t = _strip_embedded_script_code(_normalize_whitespace(c))
        if t:
            cleaned.append(t)

    if not cleaned:
        return ""

    cleaned.sort(key=len, reverse=True)
    best = cleaned[0]
    if len(best) < _JSON_LD_MIN_TEXT_LEN:
        return ""
    return best


def _extract_bloomberg_video_text(html_text: str, url: str) -> str:
    if not html_text or not _is_bloomberg_video_url(url):
        return ""
    soup = _parse_html_soup(html_text, context="bloomberg video")
    if soup is None:
        return ""

    candidates: List[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.string or tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        _collect_bloomberg_video_descriptions(data, candidates)

    desc = _extract_meta_description(soup=soup)
    if desc:
        candidates.append(desc)

    cleaned: List[str] = []
    for candidate in candidates:
        text = _normalize_whitespace(html.unescape(candidate))
        if len(text) >= _BLOOMBERG_VIDEO_DESCRIPTION_MIN_LEN and not _looks_like_bot_interstitial(text):
            cleaned.append(text)
    if not cleaned:
        return ""
    cleaned.sort(key=len, reverse=True)
    return cleaned[0]


def _host_matches(url: str, domain: str) -> bool:
    try:
        host = (urlsplit(url).hostname or "").lower()
    except Exception:
        return False
    return host == domain or host.endswith("." + domain)


def _is_bloomberg_url(url: str) -> bool:
    return _host_matches(url, "bloomberg.com")


def _is_bloomberg_video_url(url: str) -> bool:
    if not _is_bloomberg_url(url):
        return False
    try:
        path = (urlsplit(url).path or "").lower()
    except Exception:
        return False
    return "/videos/" in path or "/news/videos/" in path


def _html_fragment_to_text(fragment_html: str) -> str:
    """Convert a trusted CMS HTML body fragment into paragraph text."""
    soup = _parse_html_soup(fragment_html, context="html fragment")
    if soup is None:
        return ""
    # Embed loaders and tracking pixels ride along inside CMS article bodies. Their source is
    # never spoken content, and it would otherwise reach the reader via the get_text() fallback
    # at the end of this function.
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    blocks = soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"])
    paras: List[str] = []
    for tag in blocks:
        # Skip container blocks (e.g. a blockquote wrapping <p>s); keep the leaf blocks.
        if tag.find(["p", "li"]) is not None:
            continue
        text = _normalize_whitespace(tag.get_text(" ", strip=True))
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if text:
            paras.append(text)
    if paras:
        return "\n\n".join(paras)
    return _normalize_whitespace(soup.get_text("\n", strip=True))


def _extract_axios_story_text(html: str) -> str:
    """Extract the Axios article body from the __NEXT_DATA__ JSON blob (see note at
    _AXIOS_STORY_MIN_TEXT_LEN). Returns "" when the blob or body is missing/too short."""
    if not html or "__NEXT_DATA__" not in html:
        return ""
    soup = _parse_html_soup(html, context="axios next data")
    if soup is None:
        return ""
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None:
        return ""
    raw = tag.string or tag.get_text(strip=True)
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except Exception:
        return ""
    if not isinstance(data, dict):
        return ""

    story = data.get("props") or {}
    for key in ("pageProps", "data", "story"):
        if not isinstance(story, dict):
            return ""
        story = story.get(key) or {}
    if not isinstance(story, dict):
        return ""

    body_html = story.get("bodyHtml")
    if isinstance(body_html, dict):
        fragments = [body_html.get(k) for k in _AXIOS_BODY_HTML_KEYS]
    elif isinstance(body_html, str):
        fragments = [body_html]
    else:
        fragments = []

    texts = [_html_fragment_to_text(f) for f in fragments if isinstance(f, str) and f.strip()]
    text = _normalize_whitespace("\n\n".join(t for t in texts if t))
    if len(text) < _AXIOS_STORY_MIN_TEXT_LEN:
        return ""
    return text


_THEREGISTER_MIN_TEXT_LEN = 300
# The Register's article page opens with several teaser/"spotlight" cards (each its own
# <article>) before the story. The real body is the <article> that carries the standfirst +
# many paragraphs, so we pick the <article> with the most paragraph text rather than the first.
_THEREGISTER_DROP_LEADING_LABELS = {
    "security", "ai + ml", "ai and ml", "software", "systems", "networks", "storage",
    "devops", "personal tech", "science", "offbeat", "on-prem", "off-prem", "special features",
    "bootnotes", "emergent tech", "public sector", "legal", "cso", "spotlight",
}


def _extract_theregister_text(html: str) -> str:
    """Extract The Register's story body.

    The generic extractor grabs the "MOST POPULAR" teaser rail instead of the article, so we
    read the paragraphs straight from the story's own <article> element (the one with the most
    paragraph text) and drop the leading one-word section kicker (e.g. "Security").
    """
    soup = _parse_html_soup(html, context="theregister body")
    if soup is None:
        return ""
    best_node = None
    best_len = 0
    for node in soup.find_all("article"):
        para_len = sum(len(p.get_text(" ", strip=True)) for p in node.find_all("p"))
        if para_len > best_len:
            best_len = para_len
            best_node = node
    if best_node is None:
        return ""
    paras: List[str] = []
    for p in best_node.find_all(["p", "li"]):
        if p.find(["p", "li"]) is not None:
            continue
        text = _normalize_whitespace(p.get_text(" ", strip=True))
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if not text:
            continue
        # Drop the leading section kicker ("Security", "AI + ML", ...) that isn't part of the body.
        if not paras and text.strip().lower() in _THEREGISTER_DROP_LEADING_LABELS:
            continue
        paras.append(text)
    text = _normalize_whitespace("\n\n".join(paras))
    if len(text) < _THEREGISTER_MIN_TEXT_LEN:
        return ""
    return text


# Reuters injects zero-width characters (U+200B/C/D, word-joiner, BOM) between words as an
# anti-scraping measure. They are invisible but corrupt word matching and can make a screen
# reader stumble, so they are stripped from the extracted body.
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")
# Reuters renders external links with a visually-hidden ", opens new tab" affordance that
# get_text/trafilatura both surface as inline noise mid-sentence.
_REUTERS_OPENS_NEW_TAB_RE = re.compile(r",?\s*opens new tab\b")
_REUTERS_MIN_TEXT_LEN = 200


def _extract_reuters_text(html: str) -> str:
    """Extract Reuters' story body from its ``data-testid="paragraph-N"`` nodes.

    The generic extractor sweeps in the trailing author bio, the "Our Standards:
    The Thomson Reuters Trust Principles." line, the topics/share rail, and an
    unrelated "Read Next" recommended story (which sits outside the body, so it
    survives simple section removal). Reuters tags every real body paragraph
    ``data-testid="paragraph-N"`` inside ``data-testid="ArticleBody"``, so reading
    those directly yields the article prose and nothing else. Returns '' on any
    layout where that structure is absent, so the generic path still runs.
    """
    soup = _parse_html_soup(html, context="reuters body")
    if soup is None:
        return ""
    body = soup.select_one('[data-testid="ArticleBody"]')
    if body is None:
        return ""
    paras: List[str] = []
    for p in body.select('[data-testid^="paragraph-"]'):
        text = _REUTERS_OPENS_NEW_TAB_RE.sub("", p.get_text(" ", strip=True))
        text = _normalize_whitespace(_ZERO_WIDTH_RE.sub("", text))
        if text:
            paras.append(text)
    text = _normalize_whitespace("\n\n".join(paras))
    if len(text) < _REUTERS_MIN_TEXT_LEN:
        return ""
    return text


# Top Tech Tidbits (blind-community access-technology newsletter). Each weekly
# issue is a WordPress ``div.post-container`` split into many ``border-container-N``
# section divs — an email-style table/div layout. The generic extractor keeps only
# the small semantic ``div.post-content`` header and discards the section divs as
# boilerplate, dropping ~95% of the issue. Isolating ``post-container`` (minus
# share/subscribe/related chrome) and extracting that returns the whole issue.
_TOPTECHTIDBITS_CHROME = (
    ".sd-content", ".sharedaddy", ".jp-relatedposts",
    ".jetpack-subscription-modal", ".post-meta", ".post-byline",
)
_TOPTECHTIDBITS_MIN_TEXT_LEN = 2000


def _extract_toptechtidbits_text(html: str, url: str) -> str:
    """Extract a full Top Tech Tidbits newsletter issue (see note above).

    Returns '' when the expected structure is absent so the generic path runs.
    """
    soup = _parse_html_soup(html, context="toptechtidbits body")
    if soup is None:
        return ""
    node = soup.select_one("div.post-container")
    if node is None:
        return ""
    for selector in _TOPTECHTIDBITS_CHROME:
        for junk in node.select(selector):
            junk.decompose()
    text = _trafilatura_extract_text(str(node), url=url)
    return text if len(text or "") >= _TOPTECHTIDBITS_MIN_TEXT_LEN else ""


_GSMARENA_MIN_TEXT_LEN = 300


def _extract_gsmarena_text(html: str) -> str:
    """Extract GSMArena article/review bodies with their headings intact.

    Trafilatura drops every <h3> section heading ("Introduction", "... specs
    at a glance:", "Unboxing ...") and the specs <ul> from GSMArena's
    #review-body in every mode and output format, so the classic full-text
    view lost the article's whole structure. Read the body blocks directly in
    document order instead.
    """
    soup = _parse_html_soup(html, context="gsmarena body")
    if soup is None:
        return ""
    body = soup.select_one("#review-body") or soup.select_one("div.article-body")
    if body is None:
        return ""
    lines: List[str] = []
    for node in body.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
        if node.find(["p", "li"]) is not None:
            continue
        text = _normalize_whitespace(node.get_text(" ", strip=True))
        text = re.sub(r"\s+([,.;:!?])", r"\1", text)
        if text:
            lines.append(text)
    text = _normalize_whitespace("\n\n".join(lines))
    if len(text) < _GSMARENA_MIN_TEXT_LEN:
        return ""
    return text


# Discussion sites render a thread as a flat list of sibling post/comment blocks
# with no single node holding the conversation, so generic extraction picks the one
# block that most resembles an article and throws the rest away. On audiogames.net a
# 20-reply topic came back as one 322-character reply and the rich reader showed only
# the last poster's signature; on applevis.com the replies ran together with no way to
# tell who was speaking. Linearizing every post keeps the whole conversation, and the
# per-post header is what makes it readable aloud.
#
# Each layout names the same parts, so one linearizer serves every platform and the
# rich reader reuses it. `lead` is for engines (Drupal) where the opening post is a
# different element from the replies; FluxBB's first post is just another post.
_FORUM_LAYOUTS = (
    {   # BlindRSS semantic reconstruction of a Google Groups conversation
        "name": "googlegroups",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-googlegroups-post",
        "post_body": ".blindrss-googlegroups-body",
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # BlindRSS semantic reconstruction of a Google Help Community thread
        "name": "googlesupport",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-googlesupport-post",
        "post_body": ".blindrss-googlesupport-body",
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # BlindRSS semantic reconstruction of a Discourse JSON topic
        "name": "discourse",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-discourse-post",
        "post_body": ".blindrss-discourse-body",
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # BlindRSS semantic reconstruction of a Groups.io topic
        "name": "groupsio",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-groupsio-post",
        "post_body": ".blindrss-groupsio-body",
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # BlindRSS semantic reconstruction of a Reddit JSON/RSS thread
        "name": "reddit",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-reddit-post",
        "post_body": ".blindrss-reddit-body",
        # The generated heading already carries the stable post number, author,
        # timestamp, and reply level; do not prepend a second local counter.
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # BlindRSS semantic reconstruction of a Lemmy API thread
        "name": "lemmy",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "section.blindrss-lemmy-post",
        "post_body": ".blindrss-lemmy-body",
        "post_number": "h2",
        "post_header": (),
        "post_time": "",
        "junk": (),
    },
    {   # FluxBB / PunBB — audiogames.net
        "name": "fluxbb",
        "lead": "",
        "lead_body": "",
        "lead_header": (),
        "post": "div.post",
        "post_body": ".post-entry .entry-content",
        # `.post-num` is the number the thread itself uses ("#626"), which is what
        # posters quote at each other, so it beats a per-page counter of our own.
        "post_number": ".post-num",
        "post_header": (".post-byline",),
        "post_time": ".post-link",
        # A per-user signature repeats under every post that user makes; in a long
        # thread it would be read out dozens of times.
        "junk": (".sig-content", ".post-options", ".postfoot"),
    },
    {   # Drupal comment threads — applevis.com
        "name": "drupal",
        "lead": "article.node",
        "lead_body": ".node__content .field--name-body",
        "lead_header": (".node__meta > p",),
        "post": "article.comment",
        "post_body": ".comment__text-content",
        "post_number": "",
        # The comment's own subject line, then "By alice on Monday, July 20, 2026 - 18:46".
        "post_header": (".comment__title h3 a", ".comment__author"),
        "post_time": "",
        "junk": (".comment__links", "ul.links"),
    },
)

# FluxBB shortens a long link's visible text to "https://start … end" while the
# href stays intact. Spoken aloud (or copied out of the plain-text reader) that
# ellipsized form is useless, so anchors whose text is a truncated URL are shown
# as the URL they actually point to.
_TRUNCATED_URL_TEXT_RE = re.compile(r"(?i)^https?://\S*\s*(?:…|\.\.\.)\s*\S*$")


_FORUM_THREAD_HOSTS = ("audiogames.net", "applevis.com")
_REDDIT_THREAD_PATH_RE = re.compile(
    r"^/r/(?P<subreddit>[A-Za-z0-9_]{2,21})/comments/(?P<article>[A-Za-z0-9]+)(?:/[^/?#]*)?/?$",
    re.I,
)
_REDDIT_MORE_BATCH_SIZE = 100
_REDDIT_MAX_MORE_REQUESTS = 100
_REDDIT_MAX_COMMENTS = 10_000
_LEMMY_THREAD_PATH_RE = re.compile(r"^/post/(?P<post_id>[0-9]+)/?$", re.I)
_LEMMY_COMMENT_PAGE_SIZE = 50
_LEMMY_MAX_COMMENT_REQUESTS = 250
_LEMMY_MAX_COMMENTS = 10_000


def _reddit_thread_parts(url: str) -> Optional[Tuple[str, str]]:
    """Return ``(subreddit, article_id)`` for a Reddit thread permalink."""
    try:
        parts = urlsplit(str(url or "").strip())
        host = (parts.hostname or "").lower()
        if not (host == "reddit.com" or host.endswith(".reddit.com")):
            return None
        match = _REDDIT_THREAD_PATH_RE.match(parts.path or "")
        if not match:
            return None
        return match.group("subreddit"), match.group("article")
    except Exception:
        return None


def _is_reddit_thread_url(url: str) -> bool:
    return _reddit_thread_parts(url) is not None


def _lemmy_thread_parts(url: str) -> Optional[Tuple[str, int]]:
    """Return ``(instance origin, post id)`` for a possible Lemmy post URL.

    Lemmy is decentralized, so there is no finite host allowlist.  The strict
    numeric /post/<id> route is only a candidate; the API request later confirms
    the instance and fails closed to normal article extraction on other sites.
    """
    try:
        parts = urlsplit(str(url or "").strip())
        if (parts.scheme or "").lower() not in ("http", "https") or not parts.netloc:
            return None
        match = _LEMMY_THREAD_PATH_RE.match(parts.path or "")
        if not match:
            return None
        return f"{parts.scheme}://{parts.netloc}", int(match.group("post_id"))
    except (TypeError, ValueError):
        return None


def _is_lemmy_thread_url(url: str) -> bool:
    return _lemmy_thread_parts(url) is not None


def _is_groups_io_thread_url(url: str) -> bool:
    try:
        from core import groups_io

        return groups_io.is_thread_url(url)
    except Exception:
        return False


def _is_web_forum_thread_url(url: str) -> bool:
    try:
        from core import forum_sources

        return bool(
            forum_sources.is_google_groups_thread_url(url)
            or forum_sources.is_google_support_thread_url(url)
            or forum_sources.is_discourse_topic_url(url)
        )
    except Exception:
        return False


def _is_forum_thread_host(url: str) -> bool:
    return (
        _is_reddit_thread_url(url)
        or _is_lemmy_thread_url(url)
        or _is_groups_io_thread_url(url)
        or _is_web_forum_thread_url(url)
        or any(_host_matches(url, host) for host in _FORUM_THREAD_HOSTS)
    )


def _forum_layout_of(soup):
    """Return the layout whose reply markup this page uses, or None.

    Keyed on the reply blocks, never on the opening post alone: an applevis.com
    blog entry is the same Drupal node markup as a forum topic, and with no replies
    to interleave there is nothing for this path to add over generic extraction.
    """
    if soup is None:
        return None
    for layout in _FORUM_LAYOUTS:
        if soup.select_one(layout["post"]) is not None:
            return layout
    return None


def _forum_layout_for(html: str, url: str):
    """Parse `html` and return ``(soup, layout)``; layout is None when not a thread."""
    soup = _parse_html_soup(html, context="forum thread")
    return soup, _forum_layout_of(soup)


def _forum_node_text(node, selectors) -> str:
    """Join the text of the first match for each selector, skipping the missing ones."""
    bits = []
    for selector in selectors:
        match = node.select_one(selector) if selector else None
        if match is None:
            continue
        # A header is one line, so collapse every whitespace run — Drupal emits
        # "By AppleVis , 20  July,  2026" from its nested date spans.
        text = re.sub(r"\s+", " ", _normalize_whitespace(match.get_text(" ", strip=True)))
        text = re.sub(r"\s+([,.;:])", r"\1", text).strip()
        if text:
            bits.append(text)
    return " — ".join(bits)


def _forum_post_header(post, layout, index: int) -> str:
    """Build the "#3 Reply by alice — 2026-07-19 13:54:46" line for one post.

    The byline and timestamp are taken verbatim from the page, so they are already
    in the forum's own language and need no translation. The number is the thread's
    own where it publishes one, else this post's position on the page.
    """
    number = ""
    if layout["post_number"]:
        node = post.select_one(layout["post_number"])
        if node is not None:
            number = _normalize_whitespace(node.get_text(" ", strip=True))
    if not number:
        number = f"#{index}"
    rest = _forum_node_text(post, tuple(layout["post_header"]) + (layout["post_time"],))
    return f"{number} {rest}".strip() if rest else number


def _expand_truncated_link_text(body) -> None:
    """Replace ellipsized link text with the real href (see _TRUNCATED_URL_TEXT_RE)."""
    for anchor in body.find_all("a"):
        href = str(anchor.get("href") or "").strip()
        if not href:
            continue
        text = _normalize_whitespace(anchor.get_text(" ", strip=True))
        if text and _TRUNCATED_URL_TEXT_RE.match(text):
            anchor.string = href


def _clean_forum_body(body, layout):
    """Strip per-post junk and expand truncated links, in place."""
    for selector in layout["junk"]:
        for junk in body.select(selector):
            junk.decompose()
    _expand_truncated_link_text(body)
    # Drop the wrapper's own class/id. Drupal names the comment body
    # "field--name-comment-body comment__text-content", which the rich reader's
    # class-based chrome filter reads as a comments widget and deletes — the
    # thread rendered as headings with no text under any of them. We selected this
    # node deliberately, so its class has nothing left to tell that filter.
    for attr in ("class", "id"):
        if body.has_attr(attr):
            del body[attr]
    return body


def _forum_blocks(soup, layout):
    """Yield ``(header, body_node)`` for the opening post and every reply, in order."""
    index = 1
    if layout["lead"]:
        lead = soup.select_one(layout["lead"])
        body = lead.select_one(layout["lead_body"]) if lead is not None else None
        if body is not None:
            yield (
                f"#{index} {_forum_node_text(lead, layout['lead_header'])}".strip(),
                _clean_forum_body(body, layout),
            )
            index += 1
    for post in soup.select(layout["post"]):
        body = post.select_one(layout["post_body"])
        if body is None:
            continue
        yield (
            _forum_post_header(post, layout, index),
            _clean_forum_body(body, layout),
        )
        index += 1


def _extract_forum_thread_text(html: str, url: str) -> str:
    """Linearize a discussion thread into one attributed post per block.

    Returns '' when the page has no recognizable posts (forum index, search
    results, error page) so the generic extraction path still runs.
    """
    soup, layout = _forum_layout_for(html, url)
    if soup is None or layout is None:
        return ""
    blocks: List[str] = []
    for header, body in _forum_blocks(soup, layout):
        text = (utils.html_to_text(str(body)) or "").strip()
        if not text:
            continue
        blocks.append(f"{header}\n{text}" if header else text)
    return "\n\n".join(blocks).strip()


def _reddit_get(url: str, *, timeout: int, headers: Optional[dict] = None, params=None):
    """GET Reddit with a signed-in Firefox session when one is available."""
    try:
        from core import site_cookies

        site_cookies.refresh_reddit_cookies_from_browsers(url)
    except Exception:
        LOG.debug("Could not refresh Reddit cookies from Firefox", exc_info=True)

    request_headers = dict(headers or {})
    try:
        response = utils.safe_requests_get(
            url,
            timeout=max(1, int(timeout or 20)),
            headers=request_headers,
            params=params,
            allow_redirects=True,
        )
    except Exception:
        response = None
    if response is not None and 200 <= int(getattr(response, "status_code", 0) or 0) < 300:
        return response

    # A cookie-backed request is already paired with the matching Firefox UA and
    # TLS fingerprint by safe_requests_get.  Do not retry those cookies under a
    # contradictory Chrome/Safari identity.
    try:
        if utils._site_cookie_impersonation(url):
            return response
    except Exception:
        pass

    if not getattr(utils, "CURL_CFFI_AVAILABLE", False):
        return response
    for target in (None, "safari184"):
        try:
            candidate = utils.safe_requests_get(
                url,
                timeout=max(1, int(timeout or 20)),
                headers=request_headers,
                params=params,
                allow_redirects=True,
                impersonate=True,
                impersonate_target=target,
            )
        except Exception:
            continue
        if 200 <= int(getattr(candidate, "status_code", 0) or 0) < 300:
            return candidate
        response = candidate
    return response


def _reddit_request_json(url: str, *, timeout: int, params=None):
    response = _reddit_get(
        url,
        timeout=timeout,
        headers={"Accept": "application/json, text/json;q=0.9, */*;q=0.5"},
        params=params,
    )
    if response is None or not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
        return None
    body = _response_text(response).lstrip()
    if not body or body[:1] not in ("{", "["):
        return None
    try:
        return json.loads(body)
    except (TypeError, ValueError):
        return None


def _reddit_time_label(value) -> str:
    try:
        timestamp = float(value or 0)
        if timestamp > 0:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError, OSError):
        pass
    return ""


def _reddit_body_html(data: dict, *, opening: bool = False) -> str:
    key = "selftext_html" if opening else "body_html"
    plain_key = "selftext" if opening else "body"
    fragment = str(data.get(key) or "").strip()
    if fragment:
        # raw_json=1 normally gives literal markup; tolerate Reddit's legacy
        # entity-escaped form as well.
        if fragment.startswith("&lt;"):
            fragment = html.unescape(fragment)
        return fragment
    plain = str(data.get(plain_key) or "").strip()
    if plain:
        return "".join(
            f"<p>{html.escape(block)}</p>"
            for block in re.split(r"\n{2,}", plain)
            if block.strip()
        )
    if opening:
        target = str(data.get("url_overridden_by_dest") or data.get("url") or "").strip()
        permalink = str(data.get("permalink") or "").strip()
        if target and target != permalink and not target.endswith(permalink):
            safe_target = html.escape(target, quote=True)
            return f'<p>Linked content: <a href="{safe_target}">{html.escape(target)}</a></p>'
    return "<p>[no text available]</p>"


def _reddit_thread_document(title: str, author: str, blocks: List[dict]) -> str:
    """Build one semantic page consumed identically by text and rich readers."""
    title = str(title or "Reddit thread").strip() or "Reddit thread"
    author = str(author or "").strip()
    sections = []
    for index, block in enumerate(blocks, start=1):
        block_author = str(block.get("author") or "[deleted]").strip() or "[deleted]"
        when = _reddit_time_label(block.get("created_utc"))
        role = "Posted" if index == 1 else "Comment"
        details = f"#{index} {role} by u/{block_author}"
        if when:
            details += f" — {when}"
        if index > 1:
            try:
                depth = max(0, int(block.get("depth") or 0))
            except (TypeError, ValueError):
                depth = 0
            details += f" — Reply level {depth + 1}"
        body = str(block.get("body_html") or "").strip() or "<p>[no text available]</p>"
        sections.append(
            '<section class="blindrss-reddit-post">'
            f"<h2>{html.escape(details)}</h2>"
            f'<div class="blindrss-reddit-body">{body}</div>'
            "</section>"
        )
    if not sections:
        return ""
    meta_author = f'<meta name="author" content="{html.escape(author, quote=True)}">' if author else ""
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>{meta_author}</head><body>"
        '<article data-blindrss-reddit-thread="1">'
        + "".join(sections)
        + "</article></body></html>"
    )


def _reddit_json_to_thread_html(payload, *, thread_url: str, timeout: int) -> str:
    """Expand a Reddit thread payload, exhausting every public ``more`` node."""
    thread_parts = _reddit_thread_parts(thread_url)
    if not thread_parts or not isinstance(payload, list) or len(payload) < 2:
        return ""
    subreddit, article_id = thread_parts
    try:
        post_nodes = payload[0]["data"]["children"]
        comment_nodes = payload[1]["data"]["children"]
        post = next(node.get("data") for node in post_nodes if node.get("kind") == "t3")
    except (KeyError, TypeError, StopIteration):
        return ""
    if not isinstance(post, dict):
        return ""

    link_id = str(post.get("name") or ("t3_" + str(post.get("id") or ""))).strip()
    comments: List[dict] = []
    seen_names: Set[str] = set()
    pending_ids: List[str] = []
    queued_ids: Set[str] = set()
    pending_continue: List[str] = []
    queued_continue: Set[str] = set()

    def _queue_more(node_data: dict) -> None:
        child_ids = [str(value or "").strip() for value in (node_data.get("children") or [])]
        parent_id = str(node_data.get("parent_id") or "").strip()
        # At Reddit's maximum inline depth, a special ``id: _`` node means
        # "continue this thread".  morechildren cannot expand it; request the
        # documented comment-root route and traverse the returned subtree.
        if str(node_data.get("id") or "").strip() == "_" or "_" in child_ids:
            parent_comment_id = parent_id.removeprefix("t1_")
            if parent_comment_id and parent_comment_id not in queued_continue:
                queued_continue.add(parent_comment_id)
                pending_continue.append(parent_comment_id)
        for child_id in child_ids:
            child_id = str(child_id or "").strip()
            if (
                child_id
                and child_id != "_"
                and child_id not in queued_ids
                and ("t1_" + child_id) not in seen_names
            ):
                queued_ids.add(child_id)
                pending_ids.append(child_id)

    def _visit(node) -> None:
        if not isinstance(node, dict) or len(comments) >= _REDDIT_MAX_COMMENTS:
            return
        kind = str(node.get("kind") or "")
        data = node.get("data") or {}
        if not isinstance(data, dict):
            return
        if kind == "more":
            _queue_more(data)
            return
        if kind != "t1":
            return
        name = str(data.get("name") or ("t1_" + str(data.get("id") or ""))).strip()
        if not name:
            return
        if name not in seen_names:
            seen_names.add(name)
            comments.append(data)
        replies = data.get("replies")
        if isinstance(replies, dict):
            for child in ((replies.get("data") or {}).get("children") or []):
                _visit(child)

    for node in comment_nodes or []:
        _visit(node)

    requested: Set[str] = set()
    request_count = 0
    while (
        (pending_ids or pending_continue)
        and request_count < _REDDIT_MAX_MORE_REQUESTS
        and len(comments) < _REDDIT_MAX_COMMENTS
    ):
        if not pending_ids:
            parent_comment_id = pending_continue.pop(0)
            request_count += 1
            continuation = _reddit_request_json(
                f"https://www.reddit.com/r/{subreddit}/comments/"
                f"{article_id}/_/{parent_comment_id}.json",
                timeout=timeout,
                params={"raw_json": "1", "limit": "500", "depth": "10", "sort": "confidence"},
            )
            try:
                continuation_nodes = continuation[1]["data"]["children"]
            except (KeyError, IndexError, TypeError):
                continue
            for thing in continuation_nodes or []:
                _visit(thing)
            continue
        batch = []
        while pending_ids and len(batch) < _REDDIT_MORE_BATCH_SIZE:
            child_id = pending_ids.pop(0)
            if child_id in requested:
                continue
            requested.add(child_id)
            batch.append(child_id)
        if not batch:
            continue
        request_count += 1
        more_payload = _reddit_request_json(
            "https://www.reddit.com/api/morechildren.json",
            timeout=timeout,
            params={
                "api_type": "json",
                "link_id": link_id,
                "children": ",".join(batch),
                "limit_children": "false",
                "sort": "confidence",
                "raw_json": "1",
            },
        )
        try:
            things = more_payload["json"]["data"]["things"]
        except (KeyError, TypeError):
            break
        for thing in things or []:
            _visit(thing)

    # Rebuild parent/child order after morechildren's flat response.  Initial
    # ordering is preserved within each parent, and inaccessible/orphaned nodes
    # are still appended so available comments are never silently discarded.
    by_name = {
        str(item.get("name") or ("t1_" + str(item.get("id") or ""))): item
        for item in comments
    }
    children_by_parent = {}
    for item in comments:
        parent = str(item.get("parent_id") or link_id)
        children_by_parent.setdefault(parent, []).append(item)
    ordered: List[Tuple[dict, int]] = []
    emitted: Set[str] = set()

    def _emit(parent_name: str, depth: int) -> None:
        for item in children_by_parent.get(parent_name, []):
            name = str(item.get("name") or ("t1_" + str(item.get("id") or "")))
            if not name or name in emitted:
                continue
            emitted.add(name)
            ordered.append((item, depth))
            _emit(name, depth + 1)

    _emit(link_id, 0)
    for name, item in by_name.items():
        if name not in emitted:
            emitted.add(name)
            ordered.append((item, max(0, int(item.get("depth") or 0))))

    blocks = [{
        "author": post.get("author"),
        "created_utc": post.get("created_utc"),
        "depth": 0,
        "body_html": _reddit_body_html(post, opening=True),
    }]
    for item, depth in ordered:
        blocks.append({
            "author": item.get("author"),
            "created_utc": item.get("created_utc"),
            "depth": depth,
            "body_html": _reddit_body_html(item),
        })
    return _reddit_thread_document(
        str(post.get("title") or "Reddit thread"),
        str(post.get("author") or ""),
        blocks,
    )


def _reddit_rss_thread_html(thread_url: str, *, timeout: int) -> str:
    """Best-effort fallback when Reddit refuses the JSON comments endpoint."""
    parts = _reddit_thread_parts(thread_url)
    if not parts:
        return ""
    subreddit, article_id = parts
    rss_url = f"https://www.reddit.com/r/{subreddit}/comments/{article_id}/.rss?limit=500"
    response = _reddit_get(
        rss_url,
        timeout=timeout,
        headers={"Accept": "application/atom+xml, application/rss+xml;q=0.9, */*;q=0.5"},
    )
    if response is None or not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
        return ""
    try:
        import feedparser

        parsed = feedparser.parse(getattr(response, "content", b"") or _response_text(response))
    except Exception:
        return ""
    blocks = []
    seen = set()
    for entry in getattr(parsed, "entries", []) or []:
        entry_id = str(entry.get("id") or entry.get("link") or "").strip()
        if entry_id and entry_id in seen:
            continue
        if entry_id:
            seen.add(entry_id)
        content = ""
        values = entry.get("content") or []
        if values:
            content = str(values[0].get("value") or "")
        content = content or str(entry.get("summary") or "")
        if not content.strip():
            continue
        created = 0
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            try:
                created = datetime(*parsed_time[:6], tzinfo=timezone.utc).timestamp()
            except (TypeError, ValueError, OverflowError):
                created = 0
        blocks.append({
            "author": entry.get("author") or "[deleted]",
            "created_utc": created,
            "depth": 0,
            "body_html": content,
        })
    if not blocks:
        return ""
    feed = getattr(parsed, "feed", {}) or {}
    title = str(feed.get("title") or "Reddit thread")
    return _reddit_thread_document(title, str(blocks[0].get("author") or ""), blocks)


def _download_reddit_thread_html(url: str, timeout: int = 20) -> str:
    """Fetch a Reddit submission plus every comment Reddit makes available."""
    parts = _reddit_thread_parts(url)
    if not parts:
        return ""
    subreddit, article_id = parts
    payload = _reddit_request_json(
        f"https://www.reddit.com/r/{subreddit}/comments/{article_id}.json",
        timeout=timeout,
        params={"raw_json": "1", "limit": "500", "depth": "10", "sort": "confidence"},
    )
    thread_html = _reddit_json_to_thread_html(payload, thread_url=url, timeout=timeout)
    if thread_html:
        return thread_html
    return _reddit_rss_thread_html(url, timeout=timeout)


def _lemmy_request_json(url: str, *, timeout: int, params=None):
    """Return a Lemmy API response as JSON, or None without disturbing fallback."""
    try:
        response = utils.safe_requests_get(
            url,
            timeout=max(1, int(timeout or 20)),
            headers={"Accept": "application/json, text/json;q=0.9, */*;q=0.5"},
            params=params,
            allow_redirects=True,
        )
    except Exception:
        return None
    if not (200 <= int(getattr(response, "status_code", 0) or 0) < 300):
        return None
    try:
        data = response.json()
    except Exception:
        try:
            data = json.loads(_response_text(response))
        except (TypeError, ValueError):
            return None
    return data if isinstance(data, dict) else None


def _lemmy_markdown_html(value: object) -> str:
    """Render Lemmy Markdown safely while retaining links, lists, and headings."""
    source = str(value or "").strip()
    if not source:
        return ""
    # Escaping first disables Markdown's raw-HTML passthrough.  API content is
    # user-controlled, while the rich reader should accept only generated markup.
    source = html.escape(source, quote=False)
    try:
        import markdown

        rendered = markdown.markdown(source, extensions=("extra", "sane_lists"))
        if rendered.strip():
            return rendered
    except Exception:
        LOG.debug("Could not render Lemmy Markdown", exc_info=True)
    return "".join(
        f"<p>{block}</p>"
        for block in re.split(r"\n{2,}", source)
        if block.strip()
    )


def _lemmy_time_label(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError, OverflowError):
        return raw


def _lemmy_actor_name(view: dict) -> str:
    creator = view.get("creator") or {}
    if not isinstance(creator, dict):
        return "[deleted]"
    return str(creator.get("display_name") or creator.get("name") or "[deleted]").strip()


def _lemmy_comment_depth(comment: dict) -> int:
    path = str(comment.get("path") or "").strip(".")
    parts = [part for part in path.split(".") if part and part != "0"]
    return max(0, len(parts) - 1)


def _lemmy_post_body_html(post: dict) -> str:
    if post.get("removed"):
        return "<p>[removed]</p>"
    if post.get("deleted"):
        return "<p>[deleted]</p>"
    chunks = []
    body = _lemmy_markdown_html(post.get("body"))
    if body:
        chunks.append(body)
    target = str(post.get("url") or "").strip()
    ap_id = str(post.get("ap_id") or "").strip()
    if target and target != ap_id:
        safe_target = html.escape(target, quote=True)
        chunks.append(
            f'<p>Linked content: <a href="{safe_target}">{html.escape(target)}</a></p>'
        )
    return "".join(chunks) or "<p>[no text available]</p>"


def _lemmy_comment_body_html(comment: dict) -> str:
    if comment.get("removed"):
        return "<p>[removed]</p>"
    if comment.get("deleted"):
        return "<p>[deleted]</p>"
    return _lemmy_markdown_html(comment.get("content")) or "<p>[no text available]</p>"


def _lemmy_thread_document(post_view: dict, comments: List[dict]) -> str:
    post = post_view.get("post") or {}
    if not isinstance(post, dict) or not post.get("id"):
        return ""
    title = str(post.get("name") or "Lemmy thread").strip() or "Lemmy thread"
    author = _lemmy_actor_name(post_view)
    blocks = [{
        "author": author,
        "published": post.get("published"),
        "depth": None,
        "body_html": _lemmy_post_body_html(post),
    }]
    for view in comments:
        comment = view.get("comment") or {}
        if not isinstance(comment, dict):
            continue
        blocks.append({
            "author": _lemmy_actor_name(view),
            "published": comment.get("published"),
            "depth": _lemmy_comment_depth(comment),
            "body_html": _lemmy_comment_body_html(comment),
        })

    sections = []
    for index, block in enumerate(blocks, start=1):
        role = "Posted" if index == 1 else "Comment"
        details = f"#{index} {role} by @{block['author']}"
        when = _lemmy_time_label(block.get("published"))
        if when:
            details += f" — {when}"
        if index > 1:
            details += f" — Reply level {int(block.get('depth') or 0) + 1}"
        sections.append(
            '<section class="blindrss-lemmy-post">'
            f"<h2>{html.escape(details)}</h2>"
            f'<div class="blindrss-lemmy-body">{block["body_html"]}</div>'
            "</section>"
        )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        f'<meta name="author" content="{html.escape(author, quote=True)}">'
        '</head><body><article data-blindrss-lemmy-thread="1">'
        + "".join(sections)
        + "</article></body></html>"
    )


def _lemmy_api_thread_html(origin: str, post_id: int, *, api_version: int, timeout: int) -> str:
    api_root = f"{origin}/api/v{api_version}"
    post_payload = _lemmy_request_json(
        f"{api_root}/post", timeout=timeout, params={"id": post_id}
    )
    post_view = (post_payload or {}).get("post_view")
    if not isinstance(post_view, dict):
        return ""

    comments: List[dict] = []
    seen_ids: Set[str] = set()
    cursor = ""
    for page in range(1, _LEMMY_MAX_COMMENT_REQUESTS + 1):
        params = {
            "post_id": post_id,
            "sort": "Old",
            "max_depth": 999,
            "limit": _LEMMY_COMMENT_PAGE_SIZE,
        }
        if api_version >= 4:
            if cursor:
                params["page_cursor"] = cursor
        else:
            params["page"] = page
        payload = _lemmy_request_json(
            f"{api_root}/comment/list", timeout=timeout, params=params
        )
        page_comments = (payload or {}).get("comments")
        if not isinstance(page_comments, list):
            return "" if page == 1 else _lemmy_thread_document(post_view, comments)
        new_count = 0
        for view in page_comments:
            if not isinstance(view, dict):
                continue
            comment = view.get("comment") or {}
            comment_id = str(comment.get("id") or comment.get("ap_id") or "").strip()
            if not comment_id or comment_id in seen_ids:
                continue
            seen_ids.add(comment_id)
            comments.append(view)
            new_count += 1
            if len(comments) >= _LEMMY_MAX_COMMENTS:
                break
        if len(comments) >= _LEMMY_MAX_COMMENTS or not page_comments or not new_count:
            break
        if api_version >= 4:
            next_cursor = str((payload or {}).get("next_page") or "").strip()
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
        elif len(page_comments) < _LEMMY_COMMENT_PAGE_SIZE:
            break
    return _lemmy_thread_document(post_view, comments)


def _download_lemmy_thread_html(url: str, timeout: int = 20) -> str:
    """Fetch a Lemmy post plus every comment exposed by its instance API."""
    parts = _lemmy_thread_parts(url)
    if not parts:
        return ""
    origin, post_id = parts
    # v3 serves current 0.19 instances such as rblind.com.  v4 is the Lemmy 1.0
    # interface and uses cursor pagination; accepting both keeps other instances
    # working as they upgrade independently.
    for api_version in (3, 4):
        thread_html = _lemmy_api_thread_html(
            origin, post_id, api_version=api_version, timeout=timeout
        )
        if thread_html:
            return thread_html
    return ""


def _extract_without_dom_boilerplate(html: str, url: str, selectors: Tuple[str, ...]) -> str:
    """Run normal extraction after removing known non-article DOM sections."""
    soup = _parse_html_soup(html, context="site boilerplate removal")
    if soup is None:
        return ""
    removed = False
    for selector in selectors:
        for node in soup.select(selector):
            node.decompose()
            removed = True
    if not removed:
        return ""
    return _trafilatura_extract_text(str(soup), url=url)


# socast / Pattison Interactive "Portals" radio-station CMS (used by many local
# news sites, e.g. fraservalleytoday.ca). It splits the story body across a lead in
# div.wpb-content-wrapper and a continuation in a second <article class="mainArticle">
# inside an sc-content column, with related-post / newsletter / ad widgets interleaved.
# The generic extractor picks only the short lead, so both text and rich views lose
# most of the story. These class tokens mark the interleaved non-body widgets to skip.
_SOCAST_JUNK_CLASS_TOKENS = (
    "posts", "items-wrapper", "bnl-pp-happening", "bnl-info", "bnl-title",
    "bnl-content", "pp-more-wrapper", "wpb_raw_html", "wpb_raw_code",
    "sc-author", "entry-footer", "entry-meta", "report_an_error",
    "highlight-text", "newsletter", "scwidgetcontainer", "sc-item-detail",
)


def _is_socast_page(html: str) -> bool:
    """True for socast/Pattison-portals radio-CMS article pages (split-body layout)."""
    if not html:
        return False
    low = html.lower()
    if "socastsrm.com" in low:
        return True
    # Theme fingerprint when the CDN host is absent: the split-body class trio.
    return (
        "wpb-content-wrapper" in low
        and "mainarticle" in low
        and "sc-content" in low
    )


def _socast_node_in_junk(node) -> bool:
    for ancestor in node.parents:
        joined = " ".join(ancestor.get("class") or []).lower()
        if joined and any(tok in joined for tok in _SOCAST_JUNK_CLASS_TOKENS):
            return True
    return False


def _extract_socast_text(html: str, url: str) -> str:
    """Rebuild a socast story body from its split containers, skipping the interleaved
    related-post/newsletter/ad widgets. Returns body text only (no title)."""
    soup = _parse_html_soup(html, context="socast body")
    if soup is None:
        return ""
    paras: List[str] = []
    seen: Set[str] = set()
    for container in soup.select("div.wpb-content-wrapper, article.mainArticle"):
        for node in container.find_all(["p", "li"]):
            # Skip container paragraphs (a <p> wrapping other <p>/<li>) to avoid dupes.
            if node.find(["p", "li"]) is not None:
                continue
            if _socast_node_in_junk(node):
                continue
            text = _normalize_whitespace(node.get_text(" ", strip=True))
            if not text:
                continue
            key = _normalize_for_match(text)
            if key in seen:
                continue
            seen.add(key)
            paras.append(text)
    return _normalize_whitespace("\n\n".join(paras))


def _extract_site_specific_text(html: str, url: str) -> str:
    """Site-specific structured body extraction that outranks generic heuristics."""
    if _is_bloomberg_video_url(url):
        return _extract_bloomberg_video_text(html, url)
    if _host_matches(url, "axios.com"):
        return _extract_axios_story_text(html)
    if _host_matches(url, "theregister.com") or _host_matches(url, "theregister.co.uk"):
        return _extract_theregister_text(html)
    if _host_matches(url, "reuters.com"):
        return _extract_reuters_text(html)
    if _host_matches(url, "toptechtidbits.com"):
        return _extract_toptechtidbits_text(html, url)
    if _host_matches(url, "gsmarena.com"):
        return _extract_gsmarena_text(html)
    if _host_matches(url, "thepostmillennial.com"):
        return _extract_without_dom_boilerplate(html, url, ("section.contributions-container",))
    if _host_matches(url, "rebelnews.com"):
        return _extract_without_dom_boilerplate(html, url, ("section.posts-profile",))
    if _host_matches(url, "simonwillison.net"):
        # The blog ships no <article>/<main>; each entry sits in div.entry with
        # sibling chrome — a "Recent articles" list, a metabox of tag links, a
        # sponsor banner. Trafilatura sweeps those in (trailing related links on
        # long posts; whole-page link-list rejection on short quotation posts).
        # Drop the sibling regions so only the entry body is extracted.
        return _extract_without_dom_boilerplate(
            html, url,
            ("div.recent-articles", "#sponsored-banner", "#secondary", "#ft", "#smallhead"),
        )
    if _is_forum_thread_host(url):
        return _extract_forum_thread_text(html, url)
    if _is_socast_page(html):
        return _extract_socast_text(html, url)
    return ""


def _extract_allowlisted_lead_from_html(soup: BeautifulSoup, url: str) -> str:
    try:
        host = urlsplit(url).hostname
    except Exception:
        host = None
    if not host or not isinstance(host, str):
        return ""
    host = host.lower()

    if host == "wirtualnemedia.pl" or host.endswith(".wirtualnemedia.pl"):
        node = soup.find("div", class_="wm-article-header-lead")
        if node:
            return (node.get_text(" ", strip=True) or "").strip()

    return ""


def _recover_intro_paragraphs(
    recall_text: str,
    *,
    precision_paras_norm: Set[str],
    page_title_norm: str,
    desc_hit_snippet: str,
) -> List[str]:
    intro: List[str] = []
    desc_hit = False

    for p in _split_paragraphs(recall_text)[:_LEAD_RECOVERY_MAX_SCAN_PARAS]:
        pn = _normalize_for_match(p)
        if not pn:
            continue
        if pn in precision_paras_norm:
            break
        if page_title_norm and pn == page_title_norm:
            continue
        if not _is_reasonable_lead_paragraph(p):
            continue
        if desc_hit_snippet and desc_hit_snippet in pn:
            desc_hit = True
        intro.append(p)
        if len(intro) >= _LEAD_RECOVERY_MAX_INTRO_PARAS:
            break

    if not intro or not desc_hit:
        return []
    return intro


def _attempt_lead_recovery(
    html: str,
    url: str,
    *,
    precision_text: str,
    precision_norm: str,
    do_extract: Callable[[dict], str],
) -> Optional[str]:
    if not _lead_recovery_enabled(url):
        return None

    soup = _parse_html_soup(html, context="lead recovery")
    if soup is None:
        return None

    desc = _strip_trailing_ellipsis(_extract_meta_description(soup=soup))
    desc_norm = _normalize_for_match(desc)
    if not desc_norm or len(desc_norm) < _LEAD_RECOVERY_MIN_DESC_LEN:
        return None

    desc_snippet = desc_norm[:_LEAD_RECOVERY_DESC_SNIPPET_LEN]
    desc_hit_snippet = desc_norm[:_LEAD_RECOVERY_DESC_HIT_SNIPPET_LEN]
    if desc_snippet in precision_norm:
        return None

    def _fallback_prepend_meta_desc() -> Optional[str]:
        # Fallback: when recall extraction fails to capture the meta description, prepend the
        # cleaned meta description itself (allowlist-only). This is intentionally conservative.
        if not _is_reasonable_lead_paragraph(desc):
            return None
        combined = "\n\n".join([desc, precision_text])
        return (combined or "").strip()

    lead_html = _extract_allowlisted_lead_from_html(soup, url)
    lead_html_norm = _normalize_for_match(lead_html)
    if lead_html_norm and desc_hit_snippet and desc_hit_snippet in lead_html_norm and lead_html_norm not in precision_norm:
        if _is_reasonable_lead_paragraph(lead_html):
            combined = "\n\n".join([lead_html, precision_text])
            return (combined or "").strip()

    txt_rec = do_extract({"favor_recall": True})
    rec = (txt_rec or "").strip()
    if not rec:
        return _fallback_prepend_meta_desc()

    rec_head_norm = _normalize_for_match(rec[:_LEAD_RECOVERY_MAX_RECALL_NORM_CHARS])
    if desc_snippet not in rec_head_norm:
        return _fallback_prepend_meta_desc()

    page_title = _strip_title_suffix(_extract_page_title(soup=soup))
    page_title_norm = _normalize_for_match(page_title)

    precision_paras_norm = {_normalize_for_match(p) for p in _split_paragraphs(precision_text)}

    intro = _recover_intro_paragraphs(
        rec,
        precision_paras_norm=precision_paras_norm,
        page_title_norm=page_title_norm,
        desc_hit_snippet=desc_hit_snippet,
    )
    if not intro:
        return _fallback_prepend_meta_desc()

    combined = "\n\n".join(intro + [precision_text])
    return (combined or "").strip()


_ZDNET_BOILERPLATE_PATTERNS: List[re.Pattern] = [
    re.compile(r"^\s*ZDNET\s+Recommends\b", re.I),
    re.compile(r"^\s*What\s+exactly\s+does\s+it\s+mean\?\s*$", re.I),
    re.compile(r"\bZDNET's\s+recommendations\s+are\s+based\s+on\b", re.I),
    re.compile(r"\bhours\s+of\s+testing\b", re.I),
    re.compile(r"\bcomparison\s+shopping\b", re.I),
    re.compile(r"\bvendor\s+and\s+retailer\s+listings\b", re.I),
    re.compile(r"\baffiliate\s+commissions\b", re.I),
    re.compile(r"\bdoes\s+not\s+affect\s+the\s+price\s+you\s+pay\b", re.I),
    re.compile(r"\bstrict\s+guidelines\b", re.I),
    re.compile(r"\beditorial\s+content\b.*\badvertisers\b", re.I),
    re.compile(r"\bOur\s+goal\s+is\s+to\s+deliver\b", re.I),
    re.compile(r"\bfact-?check\b", re.I),
    re.compile(r"\breport\s+the\s+mistake\b", re.I),
    re.compile(r"^\s*Follow\s+ZDNET\b", re.I),
    re.compile(r"\bAdd\s+us\s+as\s+a\s+preferred\s+source\s+on\s+Google\b", re.I),
    re.compile(r"\bpreferred\s+source\s+on\s+Google\b", re.I),
    re.compile(r"\bFollow\s+ZDNET\b", re.I),
]


def _strip_zdnet_recommends_block(text: str) -> str:
    """Backward-compatible name: strip common ZDNET boilerplate paragraphs near the top.

    ZDNET sometimes injects disclosure / recommendation / follow blocks at the start of the extracted text.
    We only remove paragraphs that match known patterns, and only within the first N paragraphs to avoid
    deleting real content.
    """
    paras = _split_paragraphs(text)
    if not paras:
        return ""

    max_scan = min(25, len(paras))
    i = 0
    while i < max_scan:
        p = (paras[i] or "").strip()
        if not p:
            i += 1
            continue

        if any(rx.search(p) for rx in _ZDNET_BOILERPLATE_PATTERNS):
            i += 1
            continue

        # A few pages split disclosure headings into tiny chunks.
        if i < 10 and re.search(r"\bZDNET\b", p, re.I) and (
            re.search(r"\brecommend", p, re.I)
            or re.search(r"\bpreferred\s+source\b", p, re.I)
            or re.search(r"\bfollow\b", p, re.I)
        ):
            i += 1
            continue

        break

    cleaned = "\n\n".join(paras[i:]).strip()
    return cleaned


def _strip_thetyee_boilerplate(text: str) -> str:
    """Remove common The Tyee fundraising boilerplate."""
    t = (text or "").strip()
    
    # 1. Top fundraising block (long text ending in 'Support Us Now')
    # Removed ^ anchor to handle cases where title or other metadata precedes it.
    t = re.sub(
        r"(?si)Our\s+[Jj]ournalism\s+is\s+supported\s+by\s+(?:readers|Tyee\s+Builders)\s+like\s+you.*?\nSupport\s+Us\s+Now\s*",
        "",
        t,
        count=1
    )
    
    # 2. Bottom subscription/privacy footer
    # "Subscribe now... Privacy policy"
    t = re.sub(
        r"(?si)Subscribe\s+now\s+Privacy\s+policy.*?Subscribe\s+now\s+Privacy\s+policy\s*",
        "",
        t
    )
    
    return t.strip()


def _strip_9to5mac_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)FTC:\s*We\s+use\s+income\s+earning\s+auto\s+affiliate\s+links\..*?More\.", "", text)
    t = re.sub(r"(?i)You(?:’|')re\s+reading\s+9to5Mac\s*(?:—|-).*?(?:loop\.|channel)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Check\s+out\s+our\s+exclusive\s+stories,.*?(?:channel|loop\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?is)\nWorth\s+checking\s+out\s+on\s+Amazon\b.*$", "", t)
    t = re.sub(r"(?is)\nFollow\s+[A-Z][^:\n]{0,60}:\s*(?:Threads|Bluesky|Instagram|Mastodon)\b.*$", "", t)
    return t


def _strip_9to5google_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nJoin\s+9to5Google\s+Pro\s+to\s+get\s+more\b.*$", "", text)


def _strip_9to5toys_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nYou(?:’|')re\s+reading\s+9to5Toys\s*(?:—|-).*$", "", text)


def _strip_postmillennial_boilerplate(text: str) -> str:
    return re.sub(r"(?is)\nJoin\s+and\s+support\s+independent\s+free\s+thinkers!.*$", "", text)

def _strip_globalnews_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)^By\s+Staff\s+The\s+Canadian\s+Press", "", text, flags=re.MULTILINE)
    t = re.sub(r"(?i)^Posted\s+\w+\s+\d+,\s+\d+\s+\d+:\d+\s+[ap]m", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)^\d+\s+min\s+read", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)If\s+you\s+get\s+Global\s+News\s+from\s+Instagram\s+or\s+Facebook.*?(?:connect\s+with\s+us\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Hide\s+message\s+barDescrease\s+article\s+font\s+size\s*Increase\s+article\s+font\s+size", "", t)
    return t

# Al Jazeera embeds a "Recommended Stories" related-articles widget INLINE in the article body,
# which extracts as a "list of N items- list 1 of N<headline>" block followed by newline-separated
# "- list K of N<headline>" lines. It sits mid-article, so it is removed in place (not truncated).
_AJ_RELATED_LIST_RE = re.compile(
    r"(?im)^(?:Recommended\s+Stories\s*\n)?"      # optional widget header on its own line
    r"list\s+of\s+\d+\s+items"                     # "list of N items"
    r"-\s*list\s+\d+\s+of\s+\d+[^\n]*"             # first item, glued to "items" (no newline)
    r"(?:\n-\s*list\s+\d+\s+of\s+\d+[^\n]*)*"      # subsequent "- list K of N ..." items
    r"\n?"
)


def _strip_aljazeera_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Published\s+On\s+\d+\s+\w+\s+\d+.*?(?:20\d\d)", "", text)
    t = re.sub(r"(?i)Click\s+here\s+to\s+share\s+on\s+social\s+media", "", t)
    t = re.sub(r"(?i)share\d+Save", "", t)
    t = _AJ_RELATED_LIST_RE.sub("\n", t)
    return t

_AXIOS_BOILERPLATE_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)^Add\s+Axios\s+as\s+(?:a|your)\s+preferred\s+source\b.*\bGoogle\.?$"),
    # Story-card metadata like "17 mins ago - Politics & Policy"
    re.compile(r"(?i)^(?:\d+\s+(?:mins?|minutes?|hours?|days?)|moments?)\s+ago\s*[-–—]\s*\S"),
    re.compile(r"(?i)^Go\s+deeper(?:\s*\(\s*\d+\s+min(?:\.|utes)?\s+read\s*\))?$"),
]

def _strip_axios_boilerplate(text: str) -> str:
    paras = _split_paragraphs(text)
    if not paras:
        return ""
    kept = [p for p in paras if not any(rx.search(p) for rx in _AXIOS_BOILERPLATE_PATTERNS)]
    return "\n\n".join(kept).strip()

def _strip_bbc_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)ShareSave", "", text)
    return t

def _strip_wsj_boilerplate(text: str) -> str:
    # Dow Jones appends a copyright line and an opaque tracking hash to article bodies
    # (e.g. "Copyright ©2026 Dow Jones & Company, Inc. All Rights Reserved. 87990cbe...").
    t = re.sub(
        r"(?is)\s*Copyright\s*©?\s*\d{4}\s*Dow\s+Jones\s*&\s*Company.*?All\s+Rights\s+Reserved\.\s*[0-9a-f]{16,}\s*$",
        "",
        text,
    )
    return t.strip()

# TechRadar (and other Future sites) append a fixed trailing block after the article body:
# a "Follow ... on Google News" / "Sign up for breaking news ..." promo, then the author's bio
# paragraph, then a two-line comment-gate notice ("You must confirm your public display name
# before commenting" / "Please logout and then login again ...").
#
# The comment-gate notice is the only DEFINITIVE end-of-article marker: it is always present and
# always trailing. The "Sign up for breaking news ..." line is NOT a safe truncation anchor because
# TechRadar also drops it inline as a newsletter widget mid-article (verified: one article had it at
# ~29% of the body). So we anchor on the comment gate, drop the author bio paragraph directly above
# it, and drop a promo/sign-up line directly above the bio; separately we remove promo/newsletter
# widget lines (exact boilerplate sentences) wherever they appear in the kept body.
_TECHRADAR_GATE_RE = re.compile(r"(?i)^You\s+must\s+confirm\s+your\s+public\s+display\s+name\s+before\s+commenting\b")
_TECHRADAR_FOLLOW_RE = re.compile(r"(?i)^Follow\s+TechRadar\b.*\b(?:Google\s+News|preferred\s+source)\b")
_TECHRADAR_SIGNUP_RE = re.compile(r"(?i)^Sign\s+up\s+for\s+breaking\s+news\b.*\btop\s+tech\s+deals\b")


def _strip_techradar_boilerplate(text: str) -> str:
    paras = _split_paragraphs(text)
    if not paras:
        return ""

    def _is_promo(p: str) -> bool:
        return bool(_TECHRADAR_FOLLOW_RE.search(p) or _TECHRADAR_SIGNUP_RE.search(p))

    cut = len(paras)
    for i, p in enumerate(paras):
        if _TECHRADAR_GATE_RE.search(p):
            cut = i
            # The author bio sits directly above the comment gate; drop it.
            if cut - 1 >= 0:
                cut -= 1
            # A promo / sign-up line sits directly above the bio; drop it too.
            if cut - 1 >= 0 and _is_promo(paras[cut - 1]):
                cut -= 1
            break
    else:
        # No comment gate: fall back to the always-trailing "Follow ... Google News" promo, which
        # (unlike the sign-up line) never appears inline.
        for i, p in enumerate(paras):
            if _TECHRADAR_FOLLOW_RE.search(p):
                cut = i
                break

    kept = [p for p in paras[:cut] if not _is_promo(p)]
    return "\n\n".join(kept).strip()

def _strip_canada_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Advertisement\s+\d+", "", text)
    t = re.sub(r"(?i)This\s+advertisement\s+has\s+not\s+loaded\s+yet.*?(?:continues\s+below\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Author\s+of\s+the\s+article:.*?(?:read)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Join\s+the\s+conversation", "", t)
    t = re.sub(r"(?i)Read\s+More.*?(?:Article\s+content)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Share\s+this\s+article\s+in\s+your\s+social\s+network", "", t)
    t = re.sub(r"(?i)Trending\s+Latest\s+National\s+Stories", "", t)
    return t

def _strip_slashdot_boilerplate(text: str) -> str:
    """Truncate at Slashdot's trailing OneTrust privacy-choices footer.

    The footer normally never reaches extraction (it lives on a separate
    OneTrust page that was only pulled in via the bogus "next story" link,
    now excluded from pagination-following), but a whole-page markdown
    fallback (e.g. Jina) can still include it, always as the trailing block.
    """
    t = re.sub(
        r"(?is)\n*#*\s*YOUR\s+PRIVACY\s+CHOICES\s*\(DO\s+NOT\s+SELL/SHARE/TARGET\).*$",
        "",
        text or "",
    )
    return t.strip()


def _strip_castanet_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)-\s+.*?\s+-\s+\d+:\d+\s+[ap]m", "", text)
    return t


def _strip_bloomberg_boilerplate(text: str) -> str:
    """Remove Bloomberg page chrome/footer when extraction falls back to page markdown."""
    original = _normalize_whitespace(text or "")
    paras = _split_paragraphs(original)
    if not paras:
        return ""

    def _is_author_line(p: str) -> bool:
        p = (p or "").strip()
        if re.match(r"(?i)^By\s+\[[^\]]+\]\(", p):
            return True
        # Bloomberg sometimes emits plain author text (e.g., "By Bloomberg News")
        return bool(re.match(r"(?i)^By\s+[A-Z][A-Za-z .,'’\\-]{1,100}$", p))

    def _is_bloomberg_meta_or_control(p: str) -> bool:
        p = (p or "").strip()
        if not p:
            return True
        if re.match(r"(?i)^(Gift this article|Add us on Google|Save|Translate|Listen)$", p):
            return True
        if re.match(r"(?i)^(Updated on|Published on)$", p):
            return True
        if re.match(r"(?i)^[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s+at\s+\d{1,2}:\d{2}\s+[AP]M\s+UTC$", p):
            return True
        if p.startswith("[Contact us: Provide news feedback or report an error]("):
            return True
        if p.startswith("[Confidential tip? Send a tip to our reporters]("):
            return True
        if p.startswith("[Site feedback: Take our Survey]("):
            return True
        if p.startswith("### **Takeaways** by Bloomberg AI") or p.startswith("### Takeaways by Bloomberg AI"):
            return True
        if p.startswith("Takeaways by Bloomberg AI"):
            return True
        return False

    def _is_bloomberg_end_marker(p: str) -> bool:
        p = (p or "").strip()
        if not p:
            return False
        if p.startswith("[Before it's here, it's on the Bloomberg Terminal"):
            return True
        if p.startswith("### More From Bloomberg") or p.startswith("### Top Reads"):
            return True
        if p.startswith("[Home](https://www.bloomberg.com/)[BTV+]"):
            return True
        if p.startswith("[Terms of Service]("):
            return True
        if "Bloomberg L.P. All Rights Reserved" in p:
            return True
        if p.startswith("Explore live news and interviews"):
            return True
        if p.startswith("Get unlimited access for just"):
            return True
        if p.startswith("By accepting, you agree to our updated [Terms of Service"):
            return True
        return False

    def _is_bloomberg_header_line(p: str) -> bool:
        return _is_author_line(p) or _is_bloomberg_meta_or_control(p)

    start = 0
    header_anchor_idx = None
    for i, p in enumerate(paras):
        if _is_author_line(p):
            header_anchor_idx = i
            break
    if header_anchor_idx is None:
        for i, p in enumerate(paras):
            if _is_bloomberg_meta_or_control(p):
                header_anchor_idx = i
                break

    if header_anchor_idx is not None:
        seq_start = header_anchor_idx
        while seq_start > 0 and _is_bloomberg_header_line(paras[seq_start - 1]):
            seq_start -= 1

        i = seq_start
        while i < len(paras) and _is_bloomberg_header_line(paras[i]):
            i += 1
        if i < len(paras):
            start = i

    end = len(paras)
    for i in range(start, len(paras)):
        if _is_bloomberg_end_marker(paras[i]):
            end = i
            break

    cleaned = "\n\n".join(paras[start:end]).strip()
    return cleaned or original


_NING_ACTIVITY_ACTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"(?i)^posted\s+a\s+\w[\w -]*$"),
    re.compile(r"(?i)^posted\s+blog\s+posts?$"),
    re.compile(r"(?i)^updated\s+their$"),
    re.compile(r"(?i)^replied(?:\s+to)?$"),
    re.compile(r"(?i)^commented(?:\s+on)?$"),
    re.compile(r"(?i)^liked$"),
    re.compile(r"(?i)^shared$"),
]


def _strip_ning_activity_noise(text: str) -> str:
    """Trim wrapper text emitted by Ning activity feed HTML fragments.

    Keep the real story title / excerpt / reply text, but drop small action wrappers
    like "posted a video" and "1 more…".
    """
    original = _normalize_whitespace(text or "")
    paras = _split_paragraphs(original)
    if not paras:
        return ""

    def _is_more_link_line(p: str) -> bool:
        s = (p or "").strip()
        if not s:
            return True
        if re.fullmatch(r"(?i)see\s+more", s):
            return True
        if re.fullmatch(r"(?i)\d+\s+more(?:\.{3}|…)?", s):
            return True
        return False

    def _is_action_line(p: str) -> bool:
        s = (p or "").strip()
        return any(rx.fullmatch(s) for rx in _NING_ACTIVITY_ACTION_PATTERNS)

    def _looks_like_actor_name(p: str) -> bool:
        s = (p or "").strip()
        if not s or len(s) > 120:
            return False
        low = s.lower()
        # Avoid matching actual content/excerpts.
        if any(tok in low for tok in ("http://", "https://", "posted ", "replied", "commented", "updated ")):
            return False
        # Mostly name-ish text: letters/numbers/basic punctuation.
        return bool(re.fullmatch(r"[\w .,'’()&+\-†]+", s))

    cleaned = [p for p in paras if not _is_more_link_line(p)]

    # Remove a common Ning wrapper prefix:
    #   <actor name>
    #   posted a video / posted blog posts / updated their / ...
    # only when there is meaningful content after it.
    if len(cleaned) >= 4 and _looks_like_actor_name(cleaned[0]) and _is_action_line(cleaned[1]):
        # For profile updates with no real excerpt, keep the small text.
        tail = cleaned[2:]
        meaningful_tail = [p for p in tail if len((p or "").strip()) >= 12]
        if len(meaningful_tail) >= 2 or any(len((p or "").strip()) >= 40 for p in meaningful_tail):
            cleaned = tail

    # If the resulting first line is just "profile" and there is other content, drop it.
    if len(cleaned) > 1 and str(cleaned[0] or "").strip().lower() == "profile":
        cleaned = cleaned[1:]

    out = "\n\n".join(cleaned).strip()
    return out or original


# Leaked <script>/<style> SOURCE in extracted text.
#
# Some CMSes build the JSON-LD ``articleBody`` (and some proxies build their plain-text
# rendering) by running a naive tag-stripper over the rendered article HTML: it deletes the
# <script> ELEMENT but keeps its JavaScript as "text". The reader then speaks the page's code
# after the last paragraph -- e.g. every mashable.com story carrying a Reddit/social embed
# trails its lazy-loader, "let cbeScripts = ... new cbeScriptObserver(item, cbeScripts[item])".
#
# Strong markers: DOM/analytics glue that prose never contains.
_CODE_STRONG_RE = re.compile(
    r"document\.(?:querySelector|querySelectorAll|getElementById|getElementsBy\w+"
    r"|createElement|head|body|cookie|write)\b"
    r"|window\.(?:addEventListener|attachEvent|dataLayer|location\.href|onload)\b"
    r"|window\[[^\]]{1,60}\]\s*="
    r"|\.addEventListener\s*\("
    r"|\bnew\s+(?:IntersectionObserver|MutationObserver|XMLHttpRequest|ResizeObserver)\s*\("
    r"|\bconsole\.(?:log|warn|error|info|debug)\s*\("
    r"|=>\s*\{"
    r"|\bfunction\s*\*?\s*\("
    r"|\bJSON\.(?:parse|stringify)\s*\("
    r"|\bdataLayer\.push\s*\(|\bgoogletag\b|\bgtag\s*\("
)
# Structural lines: declarations, control flow, dotted calls/assignments, and the brace/paren
# rubble between them. Weak on their own -- only counted inside a run that also has a strong hit.
_CODE_STRUCT_RE = re.compile(
    r"^(?:let|const|var)\s+[A-Za-z_$][\w$]*\s*[=;]"
    r"|^(?:function|if|for|while|switch|try|catch|else|return|throw|import|export|await)\b\s*[({;]"
    r"|^new\s+[A-Za-z_$][\w$]*\s*\("
    r"|^[\[\]{}();,]+$"
    r"|^[}\])][\s)\]};,]*(?:\{|\(|,\s*\{)"
    r"|^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+\s*(?:=[^=]|\()"
)

# A run must be this many code lines, with this many strong hits, before it is dropped. Tech
# stories legitimately quote short snippets (the very article that exposed this bug prints two
# `sudo defaults write` commands), so one stray match must never eat content.
_CODE_RUN_MIN_LINES = 4
_CODE_RUN_MIN_STRONG = 2


def _classify_code_line(line: str) -> Tuple[bool, bool]:
    """Return (is_code_like, is_strong_marker) for one line of extracted text."""
    s = line.strip()
    if not s:
        return False, False
    if _CODE_STRONG_RE.search(s):
        return True, True
    return bool(_CODE_STRUCT_RE.match(s)), False


def _strip_embedded_script_code(text: str) -> str:
    """Drop runs of leaked <script>/<style> source from otherwise-clean article text.

    Scans for maximal runs of code-shaped lines (blank lines do not break a run) and removes
    only those that clear both thresholds above. No-op when nothing matches, when no run
    qualifies, or when removal would leave nothing behind.
    """
    if not text or not _CODE_STRONG_RE.search(text):
        return text
    lines = text.split("\n")
    flags = [_classify_code_line(ln) for ln in lines]
    keep = [True] * len(lines)
    i = 0
    while i < len(lines):
        if not flags[i][0]:
            i += 1
            continue
        j, last, count, strong = i, i, 0, 0
        while j < len(lines):
            if flags[j][0]:
                last, count, j = j, count + 1, j + 1
                strong += 1 if flags[j - 1][1] else 0
            elif not lines[j].strip():
                j += 1  # a blank line inside a code block does not end the run
            else:
                break
        if count >= _CODE_RUN_MIN_LINES and strong >= _CODE_RUN_MIN_STRONG:
            for k in range(i, last + 1):
                keep[k] = False
        i = max(j, i + 1)
    if all(keep):
        return text
    out = _normalize_whitespace("\n".join(ln for ln, k in zip(lines, keep) if k))
    return out or text


def _postprocess_extracted_text(text: str, url: str) -> str:
    t = _normalize_whitespace(text or "")
    if not t:
        return ""

    netloc = ""
    try:
        netloc = (urlsplit(url or "").netloc or "").lower()
    except Exception:
        netloc = ""

    if netloc.endswith("zdnet.com"):
        t = _strip_zdnet_recommends_block(t)
    elif netloc.endswith("thetyee.ca"):
        t = _strip_thetyee_boilerplate(t)
    elif "9to5mac.com" in netloc:
        t = _strip_9to5mac_boilerplate(t)
    elif "9to5google.com" in netloc:
        t = _strip_9to5google_boilerplate(t)
    elif "9to5toys.com" in netloc:
        t = _strip_9to5toys_boilerplate(t)
    elif "thepostmillennial.com" in netloc:
        t = _strip_postmillennial_boilerplate(t)
    elif "globalnews.ca" in netloc:
        t = _strip_globalnews_boilerplate(t)
    elif "aljazeera.com" in netloc:
        t = _strip_aljazeera_boilerplate(t)
    elif "axios.com" in netloc:
        t = _strip_axios_boilerplate(t)
    elif "bbc.com" in netloc or "bbc.co.uk" in netloc:
        t = _strip_bbc_boilerplate(t)
    elif "wsj.com" in netloc:
        t = _strip_wsj_boilerplate(t)
    elif "techradar.com" in netloc:
        t = _strip_techradar_boilerplate(t)
    elif "o.canada.com" in netloc or "canada.com" in netloc:
        t = _strip_canada_boilerplate(t)
    elif "castanet.net" in netloc:
        t = _strip_castanet_boilerplate(t)
    elif "slashdot.org" in netloc:
        t = _strip_slashdot_boilerplate(t)
    elif "bloomberg.com" in netloc:
        t = _strip_bloomberg_boilerplate(t)
    elif netloc.endswith(".ning.com") or netloc == "ning.com":
        t = _strip_ning_activity_noise(t)

    # Generic (all hosts): CMSes emit toolbar/ad/gallery chrome at the very top
    # of the article body — a row of social-share buttons ("Share on Facebook /
    # Bluesky / X / Copy Link", fraservalleytoday.ca), an ad placeholder
    # ("Advertisement / This advertisement has not loaded yet.", Postmedia
    # sites like vancouversun.com), or a gallery prompt ("Open this photo in
    # gallery:", theglobeandmail.com). trafilatura keeps these as leading lines,
    # so a screen reader reads several junk labels before the story starts —
    # which reads as "it grabbed the page chrome, not the article" even though
    # the full body is right there.
    t = _strip_leading_boilerplate(t)

    # Generic (all hosts): a naive upstream tag-stripper can leave inline <script>/<style>
    # SOURCE behind as body "text", so the reader speaks the page's JavaScript after the last
    # paragraph. Runs last so it also covers the proxy/fallback renderings, not just JSON-LD.
    t = _strip_embedded_script_code(t)

    # Generic (all hosts): a bare recirculation heading ("You May Also Like", "SEE ALSO:")
    # left behind mid-body by the widget it labelled. It carries no content and interrupts
    # the story with a promise of links that are not there.
    t = _strip_recirculation_labels(t)

    return _normalize_whitespace(t)


# Bare "here are some other stories" headings. The links they introduce are stripped as
# navigation, so the heading is left dangling inside the prose. Matched as a whole line only,
# with a length cap, so a sentence that merely opens with one of these words is never touched.
_RECIRCULATION_LABEL_RE = re.compile(
    r"(?i)^\s*(?:"
    r"you\s+may\s+also\s+like"
    r"|you\s+might\s+also\s+like"
    r"|(?:see|read|watch)\s+also"
    r"|related(?:\s+(?:stor(?:y|ies)|articles?|posts?|reading|coverage|content))?"
    r"|more\s+(?:like\s+this|from\s+\w+)"
    r"|recommended(?:\s+for\s+you)?"
    r"|most\s+popular"
    r"|editor'?s?\s+picks?"
    r")\s*[:—-]?\s*$"
)
_RECIRCULATION_LABEL_MAX_LEN = 32


def _strip_recirculation_labels(text: str) -> str:
    """Drop standalone recirculation heading lines anywhere in the body."""
    if not text:
        return text
    lines = text.split("\n")
    kept = [
        ln for ln in lines
        if not (len(ln.strip()) <= _RECIRCULATION_LABEL_MAX_LEN
                and _RECIRCULATION_LABEL_RE.match(ln))
    ]
    if len(kept) == len(lines):
        return text
    out = _normalize_whitespace("\n".join(kept))
    return out or text


# A leading social-share/toolbar button row: each entry is a short label on its
# own line. Only exact whole-line matches of known button labels are stripped,
# and only from the very top, so real article prose is never touched.
_SOCIAL_SHARE_NETWORKS = (
    r"facebook|twitter|x|blue ?sky|linked ?in|reddit|whats ?app|threads|"
    r"pinterest|telegram|mastodon|flipboard|tumblr|e-?mail|messenger|"
    r"gab|truth\s*social|parler|line|viber|kakao"
)
_SOCIAL_SHARE_LINE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"share(?:\s+(?:on|to|via)\s+(?:" + _SOCIAL_SHARE_NETWORKS + r"))?"
    r"|(?:" + _SOCIAL_SHARE_NETWORKS + r")"
    r"|copy\s+link|link\s+copied|copied"
    r"|print(?:\s+article)?|save(?:\s+article)?|gift(?:\s+article)?"
    r"|comments?|tweet|listen(?:\s+to\s+(?:this\s+)?article)?"
    r")\s*$"
)


# Ad-placeholder and gallery/UI prompt lines that appear as leading chrome.
# These are exact, unambiguous non-content phrases (some longer than the
# social-share label cap), matched as whole lines only.
_LEADING_JUNK_LINE_RE = re.compile(
    r"(?i)^\s*(?:"
    r"advertisement(?:\s*\d+)?"
    r"|this\s+advertisement\s+has\s+not\s+loaded\s+yet\.?"
    r"|(?:the\s+)?story\s+continues\s+below(?:\s+advertisement)?\.?"
    r"|article\s+content"
    r"|open\s+this\s+photo\s+in\s+gallery:?"
    r"|we\s+apologi[sz]e,?\s+but\s+this\s+video\s+has\s+failed\s+to\s+load\.?"
    r"|we\s+have\s+been\s+unable\s+to\s+load[^\n]{0,60}"
    r")\s*$"
)


def _strip_leading_boilerplate(text: str) -> str:
    """Drop a leading run of toolbar/ad/gallery chrome lines.

    Consumes only consecutive leading lines that are, in full, a known
    social-share button label (Share on X, Copy Link, Facebook, ...) or a known
    ad/gallery placeholder phrase, and stops at the first real line. Share
    labels also carry a 30-char cap so a sentence that merely opens with such a
    word is never eaten. No-op unless something was removed and real text
    remains.
    """
    if not text:
        return text
    lines = text.split("\n")
    i = 0
    removed = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        is_share = len(line) <= 30 and bool(_SOCIAL_SHARE_LINE_RE.match(line))
        is_junk = bool(_LEADING_JUNK_LINE_RE.match(line))
        if is_share or is_junk:
            i += 1
            removed += 1
            continue
        break
    if removed and i < len(lines):
        return "\n".join(lines[i:]).lstrip("\n")
    return text


@dataclass
class _FetchResult:
    """Outcome of fetching a page.

    `blocked` is True when the only response we could obtain was an anti-bot/verification
    interstitial. It is distinct from a plain download failure (offline, DNS, timeout) so the caller
    can surface a clearer "open in browser" message.
    """
    html: Optional[str] = None
    blocked: bool = False


# Read-proxy markdown keeps navigation as long "[label](very-long-url)" lines that survive the
# short-line paragraph filter _merge_texts applies to proxy renderings (drop_short_paragraphs).
# Inlining link/image syntax reduces nav entries to their short labels, which that filter then
# drops, leaving the article sentences.
_MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MD_BULLET_RE = re.compile(r"(?m)^\s*[*+-]\s+")
_MD_HEADING_RE = re.compile(r"(?m)^#{1,6}\s*")


def _markdown_links_to_text(md: str) -> str:
    """Inline read-proxy markdown links/images/bullets so nav noise reduces to droppable lines.

    Also drops emphasis/heading/code markers so a screen reader never hears the raw syntax.
    """
    text = _MD_IMAGE_RE.sub("", md or "")
    text = _MD_LINK_RE.sub(lambda m: m.group(1), text)
    text = _MD_BULLET_RE.sub("", text)
    text = _MD_HEADING_RE.sub("", text)
    return text.replace("**", "").replace("`", "")


# Whole-page renderings can carry the site's cookie-consent modal as trailing sentences that
# the nav-run trim keeps (they are real prose). Cut from the first cookie-notice line onward,
# but only in the trailing half so an article that merely discusses cookies is never truncated.
_PROXY_COOKIE_BLOCK_RE = re.compile(
    r"(?im)^[^\n]{0,160}\b(?:uses?|stores?|places?)\s+cookies\b.*$"
)


def _strip_proxy_trailing_boilerplate(text: str) -> str:
    """Cut a trailing cookie-consent/preferences block from a whole-page proxy rendering."""
    text = text or ""
    match = _PROXY_COOKIE_BLOCK_RE.search(text)
    if match and match.start() > len(text) * 0.5:
        return text[: match.start()].rstrip()
    return text


def _strip_edge_nav_runs(text: str) -> str:
    """Drop the header/footer navigation runs from a whole-page rendering.

    Site chrome sits at the edges as unbroken runs of short, punctuation-free label lines
    (menus, section names, footer links); article prose is long sentences. Only the edge runs
    are removed, so short headings inside the body survive. Page titles trimmed with the header
    are re-supplied by the feed item's title at render time.
    """
    lines = (text or "").splitlines()

    def _is_nav_like(line: str) -> bool:
        # A rendered-markdown paragraph is one long line, so short edge lines are chrome even
        # when punctuated (e.g. NPR's "Wait Wait...Don't Tell Me!" menu entry).
        line = line.strip()
        if not line:
            return True
        if len(line) > _LINK_LIST_MAX_LINE_LEN:
            return False
        return len(line) <= 40 or not _LINK_LIST_SENTENCE_END_RE.search(line)

    start, end = 0, len(lines)
    while start < end and _is_nav_like(lines[start]):
        start += 1
    while end > start and _is_nav_like(lines[end - 1]):
        end -= 1
    return "\n".join(lines[start:end])


def _download_via_jina(target_url: str, timeout: int) -> Optional[str]:
    try:
        target = re.sub(r"^https?://", "", (target_url or "").strip())
        if not target:
            return None
        jina_url = f"https://r.jina.ai/http://{target}"
        headers = {
            "Accept": "text/plain, text/markdown, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = utils.safe_requests_get(jina_url, timeout=timeout, headers=headers, allow_redirects=True)
        if 200 <= r.status_code < 400 and r.text:
            text = r.text
            marker = "Markdown Content:"
            if marker in text:
                text = text.split(marker, 1)[1].strip()
            return text
    except Exception:
        return None
    return None


# Fallback fetchers (full-text extraction should survive dead links and hard blocks).
#
# Live sources first (impersonated refetch, Jina, Smry) because the user wants the CURRENT page
# text, not a stale copy; the Wayback Machine is the last resort for dead links and older
# articles. See _fetch_page for the exact order. Services that were evaluated and DON'T work
# programmatically (verified 2026-07): Archive.today serves its own CAPTCHA to non-browser
# clients even with TLS impersonation; Google Cache was discontinued in 2024; 12ft.io is dead.
# Do not re-add them without re-verifying.
#
# Wayback Machine: the availability API returns the closest snapshot; the `id_` timestamp flag
# requests the raw original HTML without the Wayback toolbar/rewriting, which extracts much
# cleaner. Smry.ai: the SSE endpoint streams a Readability-style JSON article (its own upstream
# fetch can be bot-blocked too, so it is best-effort like everything here) — never raise.
_WAYBACK_SNAPSHOT_RE = re.compile(r"^(https?://web\.archive\.org/web/\d{4,14})(?:id_)?/(.+)$")

_SMRY_STREAM_API = "https://smry.ai/api/article/auto/stream?url={quoted}&uiLocale=en"
_SMRY_MIN_TEXT_LEN = 300
_SMRY_DATA_LINE_RE = re.compile(r"^data:\s*(\{.*)$", re.M)

# A Chromium launch plus the page render needs far more headroom than an HTTP
# fetch; matches core.config's browser_feed_fallback_timeout_seconds default.
_BROWSER_FALLBACK_TIMEOUT_S = 90.0

_HTML_ACCEPT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Google News RSS article links are JavaScript-wrapped, signed redirect URLs rather than publisher
# URLs.  Following them as a normal HTTP redirect can return Google's consent page, which
# trafilatura then quite reasonably (but incorrectly) treats as the article.  Google exposes the
# target through the same short-lived signed RPC used by its own article page.  Resolve only this
# narrowly-recognized URL form, and only from the already-background full-text extraction path.
_GOOGLE_NEWS_HOSTS = {"news.google.com", "www.news.google.com"}
_GOOGLE_NEWS_BATCH_EXECUTE_URL = (
    "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
)
_GOOGLE_NEWS_RPC_ID = "Fbv4je"
_GOOGLE_NEWS_DATA_PREFIX = "%.@."
_GOOGLE_NEWS_LOCALE_QUERY = "hl=en-US&gl=US&ceid=US:en"
_GOOGLE_NEWS_OPAQUE_ID_RE = re.compile(r"[A-Za-z0-9_-]{12,}")
_GOOGLE_NEWS_MAX_TIMESTAMP = 99_999_999_999
_GOOGLE_NEWS_MAX_SIGNATURE_LENGTH = 4096
def _google_news_resolution_message() -> str:
    return _(
        "Google News could not resolve the original publisher link. "
        "Open the original link in your browser to read it."
    )

# Google serves EEA/UK (and some other) IPs a cookie-consent interstitial instead of the article
# redirect page. The resolver correctly refuses to treat that page as content, but without a
# consent state those users can never resolve ANY Google News article. The SOCS cookie carries a
# pre-declined consent (the same mechanism yt-dlp uses for YouTube); CONSENT=YES+ covers the
# older gate. Both are inert where no consent gate applies, so they are always sent.
_GOOGLE_NEWS_CONSENT_COOKIE = "SOCS=CAI; CONSENT=YES+"

# The page's preferred ``data-p`` signed request remains the first decoder path.  Some Google
# News variants instead expose these three data-n-a-* fields.  The Fbv4je endpoint accepts this
# generic request context with the page-provided opaque id, timestamp, and signature.
_GOOGLE_NEWS_GENERIC_REQUEST_CONTEXT = [
    [
        "X",
        "X",
        ["X", "X"],
        None,
        None,
        1,
        1,
        "US:en",
        None,
        1,
        None,
        None,
        None,
        None,
        None,
        0,
        1,
    ],
    "X",
    "X",
    1,
    [1, 1, 1],
    1,
    1,
    None,
    0,
    0,
    None,
    0,
]


def _is_google_news_article_url(url: str) -> bool:
    """Whether ``url`` has Google News' article-redirect path shape."""
    try:
        parts = urlsplit((url or "").strip())
        if (parts.hostname or "").lower() not in _GOOGLE_NEWS_HOSTS:
            return False
        path_parts = [part for part in (parts.path or "").split("/") if part]
        article_index = path_parts.index("articles")
        return article_index + 2 == len(path_parts)
    except (AttributeError, ValueError):
        return False


def _google_news_article_token(url: str) -> Optional[str]:
    """Return the opaque token from a Google News article URL, if it has one."""
    try:
        parts = urlsplit((url or "").strip())
        if not _is_google_news_article_url(url):
            return None
        path_parts = [part for part in (parts.path or "").split("/") if part]
        article_index = path_parts.index("articles")
        token = path_parts[article_index + 1]
    except (AttributeError, IndexError, ValueError):
        return None
    # Google currently uses URL-safe base64-like opaque tokens.  Reject anything else before it
    # reaches the signed RPC so an arbitrary news.google.com URL cannot become a resolver request.
    if not _GOOGLE_NEWS_OPAQUE_ID_RE.fullmatch(token or ""):
        return None
    return token


def _google_news_decoder_page_url(url: str) -> str:
    """Add a stable English locale to a Google News redirect page without dropping its token."""
    parts = urlsplit(url)
    query = f"{parts.query}&{_GOOGLE_NEWS_LOCALE_QUERY}" if parts.query else _GOOGLE_NEWS_LOCALE_QUERY
    return parts._replace(query=query, fragment="").geturl()


def _google_news_publisher_url(value: object) -> Optional[str]:
    """Return a safe non-Google publisher URL, or ``None`` for another Google wrapper."""
    if not isinstance(value, str):
        return None
    resolved = value.strip()
    try:
        destination = urlsplit(resolved)
    except (AttributeError, TypeError, ValueError):
        return None
    host = (destination.hostname or "").lower().rstrip(".")
    if (
        destination.scheme not in {"http", "https"}
        or not host
        or host == "google.com"
        or host.endswith(".google.com")
    ):
        return None
    return resolved


def _parse_google_news_batch_response(body: str) -> Optional[str]:
    """Extract the publisher URL from Google's line-oriented or split batchexecute response."""
    candidates = []
    for line in (body or "").splitlines():
        candidate = line.strip()
        if not candidate or candidate.startswith(")]}'"):
            continue
        try:
            candidates.append(json.loads(candidate))
        except Exception:
            continue

    # Google normally puts one JSON value per line, but occasionally splits a response value
    # across lines.  A bounded raw-decode scan accepts that transport variation without treating
    # untrusted text as a publisher URL.
    decoder = json.JSONDecoder()
    raw_body = body or ""
    index = 0
    while index < len(raw_body):
        start = raw_body.find("[", index)
        if start < 0:
            break
        try:
            rows, end = decoder.raw_decode(raw_body, start)
        except Exception:
            index = start + 1
            continue
        candidates.append(rows)
        index = end

    for rows in candidates:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, list) or len(row) < 3 or not isinstance(row[2], str):
                continue
            try:
                result = json.loads(row[2])
            except Exception:
                continue
            if not isinstance(result, list) or len(result) < 2 or result[0] != "garturlres":
                continue
            resolved = _google_news_publisher_url(result[1])
            if resolved:
                return resolved
    return None


def _google_news_timestamp(value: object) -> Optional[int]:
    """Validate the short-lived Google timestamp before using it in a signed request."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        timestamp = value
    elif isinstance(value, str) and value.strip().isdigit():
        try:
            timestamp = int(value.strip())
        except ValueError:
            return None
    else:
        return None
    if 0 < timestamp <= _GOOGLE_NEWS_MAX_TIMESTAMP:
        return timestamp
    return None


def _google_news_signature(value: object) -> Optional[str]:
    """Validate the opaque Google signature without logging or altering it."""
    if not isinstance(value, str) or not value or len(value) > _GOOGLE_NEWS_MAX_SIGNATURE_LENGTH:
        return None
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    return value


def _google_news_signed_request_from_data_p(raw_request: object, token: str) -> Optional[list]:
    """Rebuild a stable signed garturlreq from Google's preferred ``c-wiz[data-p]`` field."""
    if not isinstance(raw_request, str) or not raw_request.startswith(_GOOGLE_NEWS_DATA_PREFIX):
        return None
    encoded_args = '["garturlreq",' + raw_request[len(_GOOGLE_NEWS_DATA_PREFIX):]
    rpc_args = None
    for candidate in (encoded_args, encoded_args + "]"):
        try:
            rpc_args = json.loads(candidate)
            break
        except json.JSONDecodeError:
            continue
    if (
        isinstance(rpc_args, list)
        and len(rpc_args) == 2
        and rpc_args[0] == "garturlreq"
        and isinstance(rpc_args[1], list)
    ):
        # The fallback serialization above nests the original arguments one level deeper.
        rpc_args = [rpc_args[0], *rpc_args[1]]
    # The signed page request has the shape [garturlreq, context, token, transient...,
    # timestamp, signature].  The RPC accepts its stable prefix plus those final two values.
    if (
        not isinstance(rpc_args, list)
        or len(rpc_args) < 9
        or rpc_args[0] != "garturlreq"
        or rpc_args[2] != token
    ):
        return None
    timestamp = _google_news_timestamp(rpc_args[-2])
    signature = _google_news_signature(rpc_args[-1])
    if timestamp is None or signature is None:
        return None
    return rpc_args[:-6] + [timestamp, signature]


def _google_news_signed_request_from_attributes(page, token: str) -> Optional[list]:
    """Build Google's generic signed request from the alternate data-n-a-* decoder fields."""
    for node in page.select("[data-n-a-sg][data-n-a-ts][data-n-a-id]"):
        article_id = node.get("data-n-a-id")
        # A Google article page can contain signed related-story widgets.  The
        # fallback field must therefore belong to the exact RSS token requested,
        # otherwise a markup change could silently extract a different story.
        if (
            not isinstance(article_id, str)
            or article_id != token
            or not _GOOGLE_NEWS_OPAQUE_ID_RE.fullmatch(article_id)
        ):
            continue
        timestamp = _google_news_timestamp(node.get("data-n-a-ts"))
        signature = _google_news_signature(node.get("data-n-a-sg"))
        if timestamp is None or signature is None:
            continue
        return [
            "garturlreq",
            _GOOGLE_NEWS_GENERIC_REQUEST_CONTEXT,
            article_id,
            timestamp,
            signature,
        ]
    return None


def _google_news_signed_request_from_page(page_html: str, token: str) -> Tuple[Optional[list], str]:
    """Get one signed decoder request from the supported current Google News markup variants."""
    try:
        page = BeautifulSoup(page_html, "html.parser")
    except Exception:
        return None, "unparseable-page"
    for node in page.select("c-wiz[data-p]"):
        signed_request = _google_news_signed_request_from_data_p(node.get("data-p"), token)
        if signed_request:
            return signed_request, "data-p"
    signed_request = _google_news_signed_request_from_attributes(page, token)
    if signed_request:
        return signed_request, "data-n-a"
    return None, "missing-signed-request"


def _google_news_batch_payload(signed_request: list) -> dict:
    """Serialize a validated signed request for the narrow Fbv4je endpoint."""
    batch_payload = [[[
        _GOOGLE_NEWS_RPC_ID,
        json.dumps(signed_request, separators=(",", ":")),
        None,
        "generic",
    ]]]
    return {"f.req": json.dumps(batch_payload, separators=(",", ":"))}


def _resolve_google_news_decoder_attempt(
    page_url: str,
    token: str,
    request_timeout: float,
    impersonate_target: Optional[str],
) -> Optional[str]:
    """Run one matched browser-transport GET/POST decoder attempt, returning only a publisher URL."""
    target_label = impersonate_target or "chrome"
    try:
        page_response = utils.safe_requests_get(
            page_url,
            timeout=request_timeout,
            headers={**_HTML_ACCEPT_HEADERS, "Cookie": _GOOGLE_NEWS_CONSENT_COOKIE},
            allow_redirects=True,
            impersonate=True,
            impersonate_target=impersonate_target,
        )
        page_html = _response_text(page_response)
    except Exception:
        LOG.debug("Google News decoder %s GET failed", target_label, exc_info=True)
        return None
    page_status = getattr(page_response, "status_code", 0)
    direct_url = _google_news_publisher_url(getattr(page_response, "url", ""))
    if direct_url and 200 <= page_status < 400:
        return direct_url
    if not (200 <= page_status < 400) or not page_html:
        LOG.debug("Google News decoder %s page status=%s", target_label, page_status)
        return None
    if _looks_like_bot_interstitial(page_html):
        LOG.debug("Google News decoder %s received a consent or bot-interstitial page", target_label)
        return None

    signed_request, decoder_kind = _google_news_signed_request_from_page(page_html, token)
    if not signed_request:
        LOG.debug("Google News decoder %s has no usable signed request (%s)", target_label, decoder_kind)
        return None
    try:
        response = utils.safe_requests_post(
            _GOOGLE_NEWS_BATCH_EXECUTE_URL,
            timeout=request_timeout,
            data=_google_news_batch_payload(signed_request),
            headers={
                **_HTML_ACCEPT_HEADERS,
                "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                "Referer": "https://news.google.com/",
                "Cookie": _GOOGLE_NEWS_CONSENT_COOKIE,
            },
            allow_redirects=True,
            impersonate=True,
            impersonate_target=impersonate_target,
        )
        response_body = _response_text(response)
    except Exception:
        LOG.debug("Google News decoder %s %s POST failed", target_label, decoder_kind, exc_info=True)
        return None
    response_status = getattr(response, "status_code", 0)
    direct_url = _google_news_publisher_url(getattr(response, "url", ""))
    if direct_url and 200 <= response_status < 400:
        return direct_url
    if not (200 <= response_status < 400):
        LOG.debug("Google News decoder %s %s POST status=%s", target_label, decoder_kind, response_status)
        return None
    resolved = _parse_google_news_batch_response(response_body)
    if not resolved:
        LOG.debug("Google News decoder %s %s POST had no publisher URL", target_label, decoder_kind)
    return resolved


def _resolve_google_news_article_url(url: str, timeout: int) -> Optional[str]:
    """Resolve one Google News RSS redirect to its publisher URL, failing closed on any change."""
    token = _google_news_article_token(url)
    if not token:
        return None

    # This happens in a full-text worker, never in refresh/startup.  Keep each network operation
    # bounded even if a caller supplied a very large extraction timeout.  Start with a browser
    # TLS/HTTP fingerprint: normal requests can receive and retain Google's consent response.
    try:
        request_timeout = max(1.0, min(float(timeout or 10), 10.0))
    except (TypeError, ValueError):
        request_timeout = 10.0
    targets = _IMPERSONATE_TARGETS if getattr(utils, "CURL_CFFI_AVAILABLE", False) else (None,)
    page_url = _google_news_decoder_page_url(url)
    for impersonate_target in targets:
        resolved = _resolve_google_news_decoder_attempt(
            page_url,
            token,
            request_timeout,
            impersonate_target,
        )
        if resolved:
            return resolved
    return None


def _response_text(r) -> str:
    """Read a response body as text, tolerating curl_cffi's read-once encoding rule.

    curl_cffi raises ``ValueError`` if ``r.encoding`` is set after ``r.text`` has been accessed,
    so we set the encoding first (best-effort) and never touch it again. Returns "" on any error.
    """
    if r is None:
        return ""
    try:
        if not getattr(r, "encoding", None):
            try:
                r.encoding = "utf-8"
            except Exception:
                pass
        return r.text or ""
    except Exception:
        return ""


def _wayback_raw_url(snapshot_url: str) -> str:
    """Rewrite a Wayback snapshot URL to the raw (`id_`) form that skips the archive toolbar."""
    m = _WAYBACK_SNAPSHOT_RE.match((snapshot_url or "").strip())
    if not m:
        return snapshot_url
    return f"{m.group(1)}id_/{m.group(2)}"


def _download_via_wayback(target_url: str, timeout: int) -> Optional[str]:
    """Fetch the closest Internet Archive (Wayback Machine) snapshot of `target_url`."""
    try:
        api = "https://archive.org/wayback/available?url=" + quote(target_url, safe="")
        r = utils.safe_requests_get(api, timeout=timeout, allow_redirects=True)
        api_body = _response_text(r)
        if not (200 <= r.status_code < 300) or not api_body:
            return None
        data = json.loads(api_body)
        closest = ((data.get("archived_snapshots") or {}).get("closest") or {})
        snap = (closest.get("url") or "").strip()
        if not snap or not closest.get("available"):
            return None
        if snap.startswith("http://"):
            snap = "https://" + snap[len("http://"):]
        for candidate in (_wayback_raw_url(snap), snap):
            try:
                r2 = utils.safe_requests_get(
                    candidate, timeout=timeout, headers=dict(_HTML_ACCEPT_HEADERS), allow_redirects=True
                )
            except Exception:
                continue
            body = _response_text(r2)
            if 200 <= r2.status_code < 400 and body and not _looks_like_bot_interstitial(body):
                return body
    except Exception:
        return None
    return None


# Fingerprints for the impersonated live refetch, in order. Chrome first (the known-good
# target for feed WAFs, issue #29); Safari second because some Cloudflare-managed challenges
# 403 curl_cffi's Chrome/Firefox TLS hellos but pass its Safari one (verified live on
# neowin.net 2026-07: every chrome*/firefox* target got the challenge page, safari184 got
# the full article).
_IMPERSONATE_TARGETS = (None, "safari184")


def _download_via_impersonation(target_url: str, timeout: int) -> Optional[str]:
    """Refetch the LIVE page with a real-browser TLS/HTTP fingerprint (curl_cffi, issue #29).

    Many WAF gates (Neowin's "Performing security verification", Cloudflare, ...) only trigger on
    non-browser fingerprints, so this is the cheapest way to get the current page text.
    Degrades to a plain request when curl_cffi is unavailable (see utils.safe_requests_get).
    """
    # Without curl_cffi every target degrades to the same plain request; send it once only.
    targets = _IMPERSONATE_TARGETS if getattr(utils, "CURL_CFFI_AVAILABLE", False) else (None,)
    # A site we hold a browser session for pins that browser's User-Agent onto
    # every request. Cycling Chrome and Safari handshakes underneath it produces
    # a self-contradicting fingerprint that cannot pass and reads as forged, so
    # only the handshake matching the pinned UA is worth sending.
    session_target = utils._site_cookie_impersonation(target_url)
    if session_target:
        targets = (session_target,)
    for target in targets:
        try:
            r = utils.safe_requests_get(
                target_url,
                timeout=timeout,
                headers=dict(_HTML_ACCEPT_HEADERS),
                allow_redirects=True,
                impersonate=True,
                impersonate_target=target,
            )
        except Exception:
            continue
        body = _response_text(r)
        if 200 <= r.status_code < 400 and body and not _looks_like_bot_interstitial(body):
            return body
    return None


def _download_via_smry(target_url: str, timeout: int) -> Optional[str]:
    """Fetch article content through Smry.ai's public reader endpoint.

    The endpoint answers with a server-sent-event stream; a successful extraction arrives as an
    `event: article` whose data line is a JSON object with a Readability-style `article` payload
    (title / byline / content HTML). Errors arrive as `event: error` — treated as failure.
    """
    try:
        api = _SMRY_STREAM_API.format(quoted=quote(target_url, safe=""))
        r = utils.safe_requests_get(
            api,
            timeout=timeout,
            headers={"Accept": "text/event-stream, application/json;q=0.9, */*;q=0.8"},
            allow_redirects=True,
        )
        sse = _response_text(r)
        if not (200 <= r.status_code < 300) or not sse:
            return None
        article = None
        for m in _SMRY_DATA_LINE_RE.finditer(sse):
            try:
                payload = json.loads(m.group(1))
            except Exception:
                continue
            if isinstance(payload, dict) and isinstance(payload.get("article"), dict):
                article = payload["article"]
                break
        if not article:
            return None
        content = article.get("content")
        if not isinstance(content, str) or not content.strip():
            return None
        text_content = article.get("textContent")
        plain = text_content if isinstance(text_content, str) else re.sub(r"<[^>]+>", " ", content)
        if len(_normalize_whitespace(plain)) < _SMRY_MIN_TEXT_LEN:
            # Too short to be an article: likely a teaser, consent page, or extraction miss.
            return None
        title = article.get("title") if isinstance(article.get("title"), str) else ""
        byline = article.get("byline") if isinstance(article.get("byline"), str) else ""
        return (
            "<html><head>"
            f"<title>{html.escape(title)}</title>"
            f"<meta name=\"author\" content=\"{html.escape(byline)}\">"
            f"</head><body><article>{content}</article></body></html>"
        )
    except Exception:
        return None
    return None


def _download_sky_via_google_translate(target_url: str, timeout: int) -> Optional[str]:
    """Fetch a current Sky News article through Google's browser-facing web proxy.

    Sky's Akamai edge commonly returns a tiny 403 ``Access Denied`` page to plain requests and
    curl_cffi browser fingerprints even though the same article opens normally in Chrome.  The
    English-to-English Google Translate route fetches the live page (not a cached copy) and keeps
    the original article markup readable by the normal extraction pipeline.
    """
    try:
        parts = urlsplit((target_url or "").strip())
        if (parts.hostname or "").lower() != "news.sky.com":
            return None
        path = parts.path or "/"
        query = parts.query + ("&" if parts.query else "")
        query += "_x_tr_sl=auto&_x_tr_tl=en&_x_tr_hl=en"
        proxy_url = f"https://news-sky-com.translate.goog{path}?{query}"
        r = utils.safe_requests_get(
            proxy_url,
            timeout=timeout,
            headers=dict(_HTML_ACCEPT_HEADERS),
            allow_redirects=True,
        )
        body = _response_text(r)
        if 200 <= r.status_code < 400 and body and not _looks_like_bot_interstitial(body):
            return body
    except Exception:
        return None
    return None


def _download_via_browser(target_url: str, timeout: int) -> Optional[str]:
    """Last-resort: render the page in the invisible automated browser (SeleniumBase UC).

    Some publishers (nytimes.com and other DataDome sites) refuse every plain and
    TLS-impersonated request and are also refused by the read-proxies, so a real
    browser is the only way to reach the article at all. This is expensive (a
    serialized Chromium launch), so it runs only after every cheap fallback failed
    AND a gate was actually seen — the same evidence gate the feed path uses. A
    per-URL failure cooldown keeps a permanently blocked link from paying for a
    browser launch on every extraction attempt.
    """
    try:
        from core import browser_feed
    except Exception:
        return None
    try:
        response = browser_feed.fetch_page(
            target_url,
            timeout_s=max(float(timeout or 20), _BROWSER_FALLBACK_TIMEOUT_S),
            remember_failures=True,
        )
    except Exception:
        return None
    body = getattr(response, "text", "") if response is not None else ""
    return body or None


def _fetch_page(url: str, timeout: int = 20, encoding_override: str = "") -> _FetchResult:
    """Fetch a page, treating anti-bot/verification interstitials as a (recoverable) block.

    Note: some gates (e.g. Bloomberg's "unusual activity" page) are served with HTTP 200, so the
    response body must be inspected even on a successful status code.

    Fallback chain when the direct fetch fails (live sources first — the user wants the CURRENT
    page text; the possibly-stale Wayback snapshot is the last resort):
    1. Sky News' live Google Translate route (Sky only);
    2. impersonated refetch of the live page (real-browser TLS fingerprint, beats most WAF gates);
    3. Jina read-proxy (live; gates only);
    4. Smry.ai reader (live);
    5. Wayback Machine snapshot;
    6. the invisible automated browser (gates only — see _download_via_browser).
    """
    if not url:
        return _FetchResult()

    # Google Groups, Google Help Communities, and Discourse all expose richer
    # structured conversation data than generic article extraction can retain.
    # Each route check is strict and each decoder fails closed, so an unrelated
    # site with a similar path continues through the ordinary fetch chain.
    try:
        from core import forum_sources

        forum_html = ""
        if forum_sources.is_google_groups_thread_url(url):
            forum_html = forum_sources.download_google_groups_thread_html(
                url, timeout=timeout
            )
        elif forum_sources.is_google_support_thread_url(url):
            forum_html = forum_sources.download_google_support_thread_html(
                url, timeout=timeout
            )
        elif forum_sources.is_discourse_topic_url(url):
            forum_html = forum_sources.download_discourse_thread_html(
                url, timeout=timeout
            )
        if forum_html:
            return _FetchResult(html=forum_html)
    except Exception:
        LOG.debug("Structured web-forum reconstruction failed for %s", url, exc_info=True)

    # Groups.io's regular topic HTML is paginated (20 messages per page), while
    # the official API is cursor-paginated.  Reconstruct a single semantic page
    # through the API when configured and fall back to every public HTML page.
    if _is_groups_io_thread_url(url):
        try:
            from core import groups_io

            groups_html = groups_io.download_thread_html(url, timeout=timeout)
        except Exception:
            LOG.debug("Groups.io topic reconstruction failed for %s", url, exc_info=True)
            groups_html = ""
        if groups_html:
            return _FetchResult(html=groups_html)

    # Reddit's normal HTML progressively hydrates/collapses comment branches,
    # so scraping that DOM can never satisfy the reader's "all comments"
    # contract.  Build a complete semantic page from its comments endpoint (and
    # explicit morechildren expansion) before entering the generic HTML chain.
    if _is_reddit_thread_url(url):
        try:
            reddit_html = _download_reddit_thread_html(url, timeout=timeout)
        except Exception:
            LOG.debug("Reddit thread reconstruction failed for %s", url, exc_info=True)
            reddit_html = ""
        if reddit_html:
            return _FetchResult(html=reddit_html)

    # Lemmy's HTML client may initially render only part of a large discussion.
    # Its API exposes the complete flattened tree and stable depth paths, so use
    # that to build the same accessible semantic document as Reddit threads.
    if _is_lemmy_thread_url(url):
        try:
            lemmy_html = _download_lemmy_thread_html(url, timeout=timeout)
        except Exception:
            LOG.debug("Lemmy thread reconstruction failed for %s", url, exc_info=True)
            lemmy_html = ""
        if lemmy_html:
            return _FetchResult(html=lemmy_html)

    is_bloomberg = _is_bloomberg_url(url)
    is_bloomberg_video = _is_bloomberg_video_url(url)
    # A site with a stored browser session already goes out impersonated on the
    # first request (safe_requests_get forces the fingerprint its pinned UA
    # needs), so the impersonated refetch below would repeat that request byte
    # for byte.
    tried_impersonation_first = bool(utils._site_cookie_impersonation(url))

    def _retry_with_refreshed_clearance() -> Optional[_FetchResult]:
        """Re-read the browser's clearance for this site and try once more.

        Clearance cookies are short-lived (audiogames.net's lapse in well under
        an hour), so a gate on a site we hold a session for usually just means
        the user has re-visited it in their browser since we last looked. One
        SQLite read beats running the whole fallback chain — Jina, Smry,
        Wayback, then a serialized Chromium launch — for a page a current
        cookie fetches outright.
        """
        try:
            from core import site_cookies

            if not site_cookies.refresh_clearance_from_browsers(url):
                return None
            r = utils.safe_requests_get(
                url, timeout=timeout, headers=dict(_HTML_ACCEPT_HEADERS), allow_redirects=True
            )
            if not (200 <= r.status_code < 400):
                return None
            body = _response_text(r)
            if body and not _looks_like_bot_interstitial(body):
                return _FetchResult(html=body)
        except Exception:
            LOG.debug("Clearance refresh retry failed for %s", url, exc_info=True)
        return None

    def _try_fallbacks(*, gate_seen: bool) -> _FetchResult:
        if gate_seen:
            recovered = _retry_with_refreshed_clearance()
            if recovered is not None:
                return recovered
        if is_bloomberg_video and gate_seen:
            return _FetchResult(blocked=True)
        # Every fallback body is re-checked for interstitials so a gate served by the fallback
        # itself (or archived by it) is never stored as article text.
        candidates: List[Callable[[], Optional[str]]] = []
        if (urlsplit(url).hostname or "").lower() == "news.sky.com":
            candidates.append(lambda: _download_sky_via_google_translate(url, timeout))
        if not tried_impersonation_first:
            candidates.append(lambda: _download_via_impersonation(url, timeout))
        if gate_seen:
            candidates.append(lambda: _download_via_jina(url, timeout))
        candidates.append(lambda: _download_via_smry(url, timeout))
        candidates.append(lambda: _download_via_wayback(url, timeout))
        if gate_seen and not _has_stored_clearance(url):
            # Costly (serialized Chromium launch), so it is genuinely last and only
            # runs when a gate was actually seen: sites like nytimes.com refuse every
            # HTTP fallback above, and a real browser is the only way in.
            #
            # Skipped when we hold a clearance for the host. That cookie exists
            # because the site demands an interactive browser session, and the
            # automated browser has been measured unable to win one there (both
            # headless and headed). The per-URL cooldown does not help, since
            # every article on such a site is a new URL — so each one paid a
            # fresh ~40s launch to fail. Getting a current cookie is the fix,
            # and _retry_with_refreshed_clearance above already tried that.
            candidates.append(lambda: _download_via_browser(url, timeout))
        for fetch in candidates:
            alt = fetch()
            if alt and not _looks_like_bot_interstitial(alt):
                return _FetchResult(html=alt)
        return _FetchResult(blocked=True) if gate_seen else _FetchResult()

    try:
        if is_bloomberg:
            tried_impersonation_first = True
            body = _download_via_impersonation(url, timeout)
            if body:
                return _FetchResult(html=body)

        r = utils.safe_requests_get(
            url, timeout=timeout, headers=dict(_HTML_ACCEPT_HEADERS), allow_redirects=True
        )
        if 200 <= r.status_code < 400:
            # Issue #75: decode the raw bytes ourselves so a per-feed override
            # wins, and so the auto chain (header charset -> meta charset ->
            # utf-8) beats requests' ISO-8859-1 default for charset-less pages.
            raw = None
            try:
                raw = r.content
            except Exception:
                raw = None
            if raw:
                body = text_encoding.decode_bytes(
                    raw,
                    override=encoding_override,
                    content_type=str(r.headers.get("Content-Type", "") or ""),
                    kind="html",
                )
            else:
                r.encoding = r.encoding or "utf-8"
                body = r.text or ""
            if _looks_like_bot_interstitial(body):
                return _try_fallbacks(gate_seen=True)
            return _FetchResult(html=body)
        try:
            if r is not None and (r.status_code in (403, 503) or _looks_like_bot_interstitial(r.text or "")):
                return _try_fallbacks(gate_seen=True)
        except Exception:
            pass
        return _try_fallbacks(gate_seen=False)
    except Exception:
        return _try_fallbacks(gate_seen=False)


def _download_html(url: str, timeout: int = 20) -> Optional[str]:
    """Download a URL and return HTML as text (None on failure or block)."""
    return _fetch_page(url, timeout=timeout).html


def _extract_title_author_from_meta(html: str, url: str) -> Tuple[str, str]:
    title = ""
    author = ""

    if trafilatura is not None and extract_metadata is not None and html:
        try:
            meta = extract_metadata(html, url=url)
            if meta:
                title = (meta.title or "") if hasattr(meta, "title") else ""
                author = (meta.author or "") if hasattr(meta, "author") else ""
        except Exception:
            pass

    if not title or not author:
        try:
            soup = BeautifulSoup(html, "html.parser")
            if not title:
                t = soup.find("title")
                if t and t.get_text(strip=True):
                    title = t.get_text(strip=True)
            if not author:
                # NYT publishes the byline only as <meta name="byl" content="By ...">,
                # which trafilatura does not read; the reader header was left blank.
                candidate = _AUTHOR_BY_PREFIX_RE.sub(
                    "", _extract_meta_content(soup, _AUTHOR_META_CANDIDATES)
                ).strip()
                # `article:author` often holds a profile URL, not a name — never a byline.
                if candidate and not re.match(r"(?i)^(?:https?:)?//", candidate):
                    author = candidate
        except Exception:
            pass

    return (title or "").strip(), (author or "").strip()


def _trafilatura_extract_text(html: str, url: str = "") -> str:
    """Try to get the main article text using trafilatura.

    CPU considerations:
    - Prefer precision-first extraction to reduce boilerplate.
    - Only fall back to recall mode when the precision result is clearly too short.
    - For some sites, precision extraction may skip a lead/intro; in that case, try recall and
      prepend the missing intro paragraphs to the precision result.
    """
    if not html or trafilatura is None:
        return ""

    base_kwargs = dict(
        output_format="txt",
        include_comments=False,
        include_images=False,
        include_links=False,
        include_tables=False,
        # deduplicate must stay False: trafilatura's duplicate filter counts
        # paragraph sightings in a PROCESS-GLOBAL LRU shared by every extract
        # call, so re-extracting the same article (precision+recall passes,
        # prefetch + on-demand, revisits) drops its own paragraphs as
        # "duplicates" after ~3 sightings and full text collapses to a stub.
        deduplicate=False,
    )

    def _do_extract(extra_kwargs):
        try:
            return trafilatura.extract(
                html,
                url=url or None,
                **base_kwargs,
                **extra_kwargs,
            )
        except TypeError:
            # Older/newer trafilatura versions may not support all kwargs.
            safe_kwargs = dict(base_kwargs)
            safe_kwargs.update(extra_kwargs)
            for k in list(safe_kwargs.keys()):
                if k not in ("output_format", "include_comments", "include_images", "include_links", "include_tables", "deduplicate", "favor_recall", "favor_precision"):
                    safe_kwargs.pop(k, None)
            return trafilatura.extract(html, url=url or None, **safe_kwargs)
        except Exception:
            return ""

    # Precision-first
    txt_prec = _do_extract({"favor_precision": True, "favor_recall": False})
    prec = (txt_prec or "").strip()
    if prec and len(prec) >= _LEAD_RECOVERY_MIN_PRECISION_LEN:
        prec_norm = _normalize_for_match(prec)
        recovered = _attempt_lead_recovery(
            html,
            url,
            precision_text=prec,
            precision_norm=prec_norm,
            do_extract=_do_extract,
        )
        if recovered:
            return recovered

        return prec

    # Recall fallback (only when precision is empty/too short)
    txt_rec = _do_extract({"favor_recall": True})
    return (txt_rec or "").strip()


def _soup_extract_text(html: str) -> str:
    """Fallback: crude visible text extraction using BeautifulSoup."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        # remove obvious junk
        for tag in soup(["script", "style", "noscript", "svg", "canvas", "iframe"]):
            tag.decompose()
        # prefer main-ish containers
        main = soup.find("article") or soup.find("main")
        node = main if main else soup.body if soup.body else soup
        text = node.get_text("\n", strip=True)
        return (text or "").strip()
    except Exception:
        return ""


def _extract_article_paragraph_text(html: str) -> str:
    """Return visible article paragraphs suitable for JSON-LD lead comparison."""
    if not html:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        node = soup.find("article") or soup.find("main")
        if node is None:
            return ""
        paras: List[str] = []
        for p in node.find_all("p"):
            text = _normalize_whitespace(p.get_text(" ", strip=True))
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            if text:
                paras.append(text)
        return "\n\n".join(paras)
    except Exception:
        return ""


_LEAD_PATCH_MAX_SCAN_PARAS = 4
_LEAD_PATCH_MAX_LEAD_PARAS = 2
_LEAD_PATCH_ALIGN_SNIPPET_LEN = 60
_LEAD_PATCH_BASE_HEAD_CHARS = 400


def _prepend_missing_lead(base: str, alt: str) -> str:
    """Prepend lead paragraph(s) that only `alt` captured to `base`.

    `base` is the text we decided to keep (e.g. JSON-LD articleBody) and `alt` is the
    competing extraction (e.g. trafilatura). When `alt` opens with a couple of paragraphs
    that `base` lacks anywhere and then lines up with the very start of `base`, those
    opening paragraphs are a lede that `base`'s source dropped; re-attach them.
    """
    base_norm = _normalize_for_match(base)
    if not base_norm:
        return base
    base_head = base_norm[:_LEAD_PATCH_BASE_HEAD_CHARS]

    leads: List[str] = []
    aligned = False
    for p in _split_paragraphs(alt)[:_LEAD_PATCH_MAX_SCAN_PARAS]:
        pn = _normalize_for_match(p)
        if not pn:
            continue
        if pn[:_LEAD_PATCH_ALIGN_SNIPPET_LEN] in base_head:
            aligned = True
            break
        if pn in base_norm:
            # Present deeper in base, so base isn't simply missing its head; don't guess.
            break
        if len(leads) >= _LEAD_PATCH_MAX_LEAD_PARAS:
            break
        if not _is_reasonable_lead_paragraph(p):
            break
        leads.append(p)

    if not aligned or not leads:
        return base
    return _normalize_whitespace("\n\n".join(leads + [base]))


def _patch_json_ld_missing_lead(json_text: str, *alts: str) -> str:
    patched = _normalize_whitespace(json_text)
    for alt in alts:
        if alt:
            patched = _prepend_missing_lead(patched, _normalize_whitespace(alt))
    return patched


# Lines produced by utils.format_table_text. _merge_texts must not drop or
# de-duplicate them: rows can be shorter than its 25-char paragraph floor, and
# the fixed "End of table." marker repeats once per table.
_TABLE_MARKER_LINE_RE = re.compile(r"^(?:Table with \d+ rows? and \d+ columns?[:.]|Row \d+: .*\.$|End of table\.$)")

# Lines produced by utils.linearize_structure (opt-in heading/list/quote
# markers). Like table lines, they are intentional short lines: _merge_texts
# must keep them below its paragraph-length floor, and the fixed quote
# markers repeat once per quote so they must bypass de-duplication too.
_STRUCTURE_MARKER_LINE_RE = re.compile(
    r"^(?:Heading level [1-6]: .+|Quote:$|End of quote\.$|• .+|\d{1,3}\. .+)"
)


def _is_marker_line(line: str) -> bool:
    return bool(_TABLE_MARKER_LINE_RE.match(line) or _STRUCTURE_MARKER_LINE_RE.match(line))


def _linearize_tables_html(html: str, url: str = "") -> Tuple[str, List[str]]:
    """Replace structural HTML with accessible marker paragraphs, pre-extraction.

    Runs before all extraction passes so the linearized text flows through
    trafilatura/site-specific/soup extraction at its original position
    (trafilatura's include_tables=False otherwise drops tables entirely, and
    its include_tables=True pipe-grid loses header association for
    screen-reader users). Layout tables are left alone, keeping the old
    behavior for them. Heading/list/quote markers are opt-in Settings toggles
    (see utils.set_article_structure_options); inline children such as links
    stay in place so link-density boilerplate heuristics keep working.
    """
    if not html:
        return html, []
    opts = utils.get_article_structure_options()
    low = html.lower()
    want_tables = bool(opts.get("tables", True)) and "<table" in low
    want_headings = bool(opts.get("headings")) and "<h" in low
    want_lists = bool(opts.get("lists")) and ("<ul" in low or "<ol" in low)
    want_quotes = bool(opts.get("quotes")) and "<blockquote" in low
    want_links = bool(opts.get("links")) and "<a" in low
    if not (want_tables or want_headings or want_lists or want_quotes or want_links):
        return html, []
    soup = _parse_html_soup(html, context="structure linearization")
    if soup is None:
        return html, []
    blocks: List[str] = []
    try:
        if want_tables:
            blocks = utils.replace_tables_with_text(soup, as_paragraphs=True)
        utils.linearize_structure(
            soup, headings=want_headings, lists=want_lists, quotes=want_quotes, links=want_links
        )
    except Exception:
        LOG.debug("Structure linearization failed for %s", url, exc_info=True)
        return html, []
    if not (blocks or want_headings or want_lists or want_quotes or want_links):
        return html, []
    return str(soup), blocks


def _append_missing_tables(text: str, table_blocks: List[str], dom_text: str) -> str:
    """Append tables that the DOM extraction kept but ``text`` (JSON-LD) lacks.

    JSON-LD articleBody usually flattens or omits tables. Only blocks whose
    first data row appears in ``dom_text`` are considered — that scopes the
    patch to tables trafilatura judged to be inside the article body, so page
    furniture tables never get appended.
    """
    if not text or not table_blocks or not dom_text:
        return text
    dom_norm = _normalize_for_match(dom_text)
    text_norm = _normalize_for_match(text)
    extra: List[str] = []
    for block in table_blocks:
        lines = block.split("\n")
        first_row = next((ln for ln in lines if ln.startswith("Row ")), "")
        if not first_row:
            continue
        sig = _normalize_for_match(first_row)
        if sig in dom_norm and sig not in text_norm:
            extra.append(block)
    if not extra:
        return text
    return _normalize_whitespace(text + "\n\n" + "\n\n".join(extra))


def _extract_text_any(html: str, url: str = "") -> str:
    # Linearize data tables first so every extraction path below sees them as
    # ordinary in-place paragraphs (screen-reader-friendly header-value rows).
    html, table_blocks = _linearize_tables_html(html, url)

    # 0. Site-specific structured body (e.g. Axios __NEXT_DATA__). Some Axios page variants
    # ship no article body in the DOM, so trafilatura only finds related-story cards and the
    # "Add Axios as your preferred source ... on Google" promo; the CMS JSON always has the
    # real body, so it wins outright when present.
    site_txt = _extract_site_specific_text(html, url)
    if site_txt:
        return site_txt

    # 1. JSON-LD articleBody (often high quality on major sites), but never trusted alone:
    # some CMSes omit paragraphs from articleBody. Wired/Conde Nast drops the entire first
    # paragraph whenever the lede uses styled lead-in markup, so trafilatura always runs
    # and gets to supply a lede that JSON-LD is missing.
    json_txt = _extract_json_ld_text(html)

    # 2. Try Trafilatura
    txt = _trafilatura_extract_text(html, url=url)

    if txt and json_txt:
        txt_norm = _normalize_whitespace(txt)
        json_norm = _normalize_whitespace(json_txt)
        # If JSON-LD is significantly longer, prefer it, but re-attach any lead
        # paragraphs that only trafilatura captured, plus any in-article tables
        # the articleBody flattened away.
        if len(json_norm) > len(txt_norm) * 1.1:
            patched = _patch_json_ld_missing_lead(
                json_norm,
                txt_norm,
                _extract_article_paragraph_text(html),
            )
            return _append_missing_tables(patched, table_blocks, txt_norm)
        return txt_norm

    if json_txt:
        return _patch_json_ld_missing_lead(json_txt, _extract_article_paragraph_text(html))
    if txt:
        return _normalize_whitespace(txt)
    
    # 3. Last resort fallback
    txt = _soup_extract_text(html)
    return _normalize_whitespace(txt)


# Next-STORY navigation (a different article, not page 2 of this one). News sites mark these
# in anchor text ("Next Story"), classes, aria-labels, or data-* attributes — e.g. MacRumors
# uses data-track="next-article" on its next-article teaser.
_NEXT_STORY_NAV_RE = re.compile(r"next[\s_-]*(?:stor(?:y|ies)|articles?|posts?|read|up)\b")

# A genuine pagination control is a SHORT label ("Next", "Next Page", "Older", "Next »"...),
# never a full headline. Matching "next" as a substring anywhere in the anchor text made any
# next-story teaser whose headline contains "Next" (e.g. "Next Year's iPhone Air 2 to Feature
# Four Key Upgrades") look like pagination, merging an unrelated article into this one.
_PAGINATION_LABEL_RE = re.compile(r"(?:next|older)(?:\s+(?:page|pages|entries))?\s*(?:[›»>]+)?")


# Hosts where a single article is never truly paginated and "next" points at another story.
#   - slashdot.org: every story page has a "next story" button (?sdsrc=nextbtmnext) that points
#     at a DIFFERENT story — following it appended an unrelated article to every extraction, and
#     the newest story's button points at a malformed firehose.pl URL whose fallback fetch
#     returned the site's "YOUR PRIVACY CHOICES" OneTrust page as the final "page".
_NO_PAGINATION_FOLLOW_HOSTS = ("wired.com", "ning.com", "neowin.net", "bloomberg.com", "slashdot.org")


def _find_next_page(html: str, base_url: str) -> Optional[str]:
    """Return absolute next-page URL if present, else None."""
    if not html:
        return None

    try:
        # Hosts whose articles are single-page and whose "next" controls point at a DIFFERENT
        # story (not a continuation of this one), so following them merges unrelated text:
        #   - wired.com: "Next" links usually point to the next story.
        #   - ning.com: "next/older" controls navigate activity/thread listings.
        #   - neowin.net: abuses <link rel="next"> to point at the next article (verified: an Xbox
        #     report's rel=next pointed to an unrelated display-resolution science piece).
        try:
            host = (urlsplit(base_url).hostname or "").lower()
            if any(host == d or host.endswith("." + d) for d in _NO_PAGINATION_FOLLOW_HOSTS):
                return None
        except Exception:
            pass

        soup = BeautifulSoup(html, "html.parser")

        # 1) <link rel="next" href="...">
        link = soup.find("link", attrs={"rel": lambda v: v and "next" in (v if isinstance(v, list) else [v])})
        if link and link.get("href"):
            href = link.get("href").strip()
            if href:
                return urljoin(base_url, href)

        # 2) <a rel="next" href="...">
        a = soup.find("a", attrs={"rel": lambda v: v and "next" in (v if isinstance(v, list) else [v])})
        if a and a.get("href"):
            href = a.get("href").strip()
            if href:
                return urljoin(base_url, href)

        # 3) common "next" anchors/buttons
        for tag in soup.find_all("a", href=True):
            href = (tag.get("href") or "").strip()
            if not href:
                continue
            text = (tag.get_text(" ", strip=True) or "").lower()
            cls = " ".join(tag.get("class") or []).lower()
            aria = (tag.get("aria-label") or "").lower()

            # Avoid "Next Story"/"Next Article"/"Next Post" navigation, common on news
            # sites: the target is a DIFFERENT article. The marker can live in the text,
            # class, aria-label, or a data-* attribute (MacRumors: data-track="next-article").
            data_attrs = " ".join(
                " ".join(v) if isinstance(v, (list, tuple)) else str(v)
                for k, v in (tag.attrs or {}).items()
                if isinstance(k, str) and k.startswith("data-")
            ).lower()
            if _NEXT_STORY_NAV_RE.search(" ".join((text, cls, aria, data_attrs))):
                continue

            if (
                _PAGINATION_LABEL_RE.fullmatch(text)
                or text in (">", ">>", "›", "»")
                or "next" in cls
                or aria.startswith("next")
            ):
                absu = urljoin(base_url, href)
                # avoid obvious comment/share links
                if any(x in absu.lower() for x in ("facebook.com", "twitter.com", "x.com", "linkedin.com", "pinterest.com")):
                    continue
                return absu
    except Exception:
        return None

    return None


def _merge_texts(texts: List[str], *, drop_short_paragraphs: bool = False) -> str:
    """Merge multiple page texts while de-duplicating repeated blocks.

    ``drop_short_paragraphs`` enables the sub-25-char paragraph filter and is
    ONLY for read-proxy markdown renderings, which bypass _extract_text_any and
    keep site chrome as short label lines. HTML-extracted text must never use
    it: trafilatura already stripped boilerplate there, and real articles have
    legitimately short standalone lines — plain (unmarked) headings like
    "Sofascore", one-word paragraphs, "Pros"/"Cons" labels — that the filter
    was silently eating from the classic full-text view.

    Short lines also stay out of the dedupe set: review roundups repeat short
    headings ("Pros", "Cons") once per product, and those repeats are content.
    """
    seen: Set[str] = set()
    out: List[str] = []

    for t in texts:
        t = (t or "").strip()
        if not t:
            continue

        # de-dupe paragraph by paragraph
        paras = [p.strip() for p in t.split("\n") if p.strip()]
        merged_paras: List[str] = []
        i = 0
        while i < len(paras):
            p = paras[i]
            # Linearized table blocks are kept or dropped as a unit: their
            # lines bypass the per-line length floor and dedupe (data rows
            # are often shorter than 25 chars and the "End of table." marker
            # repeats per table), while a table repeated across pagination
            # pages is deduped on the whole block.
            if p.startswith("Table with") and _TABLE_MARKER_LINE_RE.match(p):
                block = [p]
                j = i + 1
                while j < len(paras) and _TABLE_MARKER_LINE_RE.match(paras[j]):
                    block.append(paras[j])
                    j += 1
                    if block[-1] == "End of table.":
                        break
                key = re.sub(r"\s+", " ", " ".join(block)).strip().lower()
                if key not in seen:
                    seen.add(key)
                    merged_paras.extend(block)
                i = j
                continue
            if _is_marker_line(p):
                # Stray table row/end line without its block header, or a
                # structure marker (heading/list/quote) line: keep as-is —
                # markers are intentional short lines and the fixed quote
                # markers repeat once per quote.
                merged_paras.append(p)
                i += 1
                continue
            key = re.sub(r"\s+", " ", p).strip().lower()
            if len(key) < 25:
                if drop_short_paragraphs:
                    i += 1
                    continue
                merged_paras.append(p)
                i += 1
                continue
            if key in seen:
                i += 1
                continue
            seen.add(key)
            merged_paras.append(p)
            i += 1

        if merged_paras:
            out.append("\n".join(merged_paras))

    return _normalize_whitespace("\n\n".join(out))


def extract_full_article(
    url: str, max_pages: int = 6, timeout: int = 20, metadata_sink=None, encoding: str = ""
) -> Optional[FullArticle]:
    """
    Extract full article text from a URL. Attempts to follow pagination for multi-page articles.

    Returns FullArticle or None on unsupported/empty.
    Raises ExtractionError for download/extraction failures that should be shown to the user.

    ``metadata_sink``, when given, is called once with ``(html, page_url)`` of
    the FIRST successfully downloaded page so callers can harvest structured
    metadata (see core.metadata_enrich) from HTML we already paid to fetch.
    Sink errors are swallowed — they must never affect extraction.
    """
    url = (url or "").strip()
    if not url:
        return None

    # A direct podcast enclosure has no webpage to scrape, but many MP3s carry
    # complete show notes/transcripts in a bounded leading ID3 tag.  Reuse the
    # same safe range reader as chapter extraction so classic Full Text and Rich
    # View can still expose that authored content without downloading the audio.
    if _looks_like_media_url(url):
        metadata = utils.embedded_id3_metadata(url)
        if not metadata:
            return None
        raw_content = str(metadata.get("content") or "").strip()
        text = utils.html_to_text(raw_content, include_images=True).strip()
        if not text:
            return None
        return FullArticle(
            url=url,
            title=str(metadata.get("title") or "").strip(),
            author=str(metadata.get("author") or "").strip(),
            text=text,
            html=raw_content,
        )

    # YouTube's browser page progressively hydrates its description and
    # comments, collapses reply branches, and exposes subtitles separately.
    # Reconstruct the complete accessible document through yt-dlp before the
    # generic HTML extractor gets a chance to return navigation boilerplate.
    try:
        from core import youtube_fulltext

        if youtube_fulltext.is_youtube_video_url(url):
            fields = youtube_fulltext.extract_article(url, timeout=timeout)
            if not fields or not fields.get("text"):
                raise ExtractionError(_("Could not retrieve YouTube video details."))
            return FullArticle(
                url=url,
                title=fields.get("title") or "",
                author=fields.get("author") or "",
                text=fields["text"],
            )
    except ExtractionError:
        raise
    except Exception as exc:
        LOG.debug("Structured YouTube extraction failed for %s", url, exc_info=True)
        raise ExtractionError(str(exc) or _("Could not retrieve YouTube video details."))

    if trafilatura is None:
        raise ExtractionError(_("trafilatura is not installed or failed to import. Reinstall requirements."))

    visited: Set[str] = set()
    page_texts: List[str] = []

    # Google News RSS items point to a signed JavaScript redirect, not the publisher.  Resolve it
    # before any normal page fetch so the reader never extracts Google's consent document.  This
    # function is called by the application's background full-text workers, not feed refresh.
    extraction_url = url
    prefetched_text: Optional[str] = None
    if _is_google_news_article_url(url):
        extraction_url = _resolve_google_news_article_url(url, timeout)
        if not extraction_url:
            # Local resolution requires direct Google access, which some regions block outright
            # (Russia's ISP-level block of news.google.com, Google's own restrictions on Iranian
            # IPs). The Jina read-proxy renders the redirect server-side from its own network
            # and returns the publisher page, so those users still get full text. Malformed
            # URLs (no valid token) still fail closed without any request.
            proxy_markdown = _download_via_jina(url, timeout) if _google_news_article_token(url) else None
            if not proxy_markdown or _looks_like_bot_interstitial(proxy_markdown):
                raise ExtractionError(_google_news_resolution_message())
            # The proxy already returns the rendered, readable page; running the HTML
            # extraction stack over it mis-detects the main content, so it bypasses
            # _extract_text_any and relies on _merge_texts dropping short nav lines.
            prefetched_text = _strip_edge_nav_runs(
                _strip_proxy_trailing_boilerplate(_markdown_links_to_text(proxy_markdown))
            )
            if not prefetched_text.strip():
                raise ExtractionError(_google_news_resolution_message())
            extraction_url = url

    current = extraction_url
    title = ""
    author = ""

    downloaded_any = False
    blocked = False
    used_proxy_text = False
    metered_preview = False

    # Not `for _ in ...`: that rebinds the gettext `_` to an int for the whole
    # function, so every _( ) error message below raised instead of translating.
    for _page_index in range(max_pages):
        if not current or current in visited:
            break
        visited.add(current)

        if prefetched_text is not None:
            page_texts.append(prefetched_text)
            prefetched_text = None
            downloaded_any = True
            used_proxy_text = True
            break

        # Pass the override only when set: keeps compatibility with test
        # doubles that substitute _fetch_page without the kwarg.
        if encoding:
            res = _fetch_page(current, timeout=timeout, encoding_override=encoding)
        else:
            res = _fetch_page(current, timeout=timeout)
        if res.blocked:
            blocked = True
            break
        html = res.html
        if not html:
            break
        if not downloaded_any and metadata_sink is not None:
            try:
                metadata_sink(html, current)
            except Exception:
                pass
        if not downloaded_any:
            metered_preview = _looks_like_metered_preview(html)
        downloaded_any = True

        if not title or not author:
            t, a = _extract_title_author_from_meta(html, current)
            if not title:
                title = t
            if not author:
                author = a

        page_texts.append(_extract_text_any(html, current))

        next_url = _find_next_page(html, current)
        if not next_url or next_url in visited:
            break
        current = next_url
        time.sleep(0.15)

    if not downloaded_any:
        if blocked:
            raise ExtractionError(_blocked_interstitial_message(extraction_url))
        raise ExtractionError(_("Download failed (site blocked, offline, or connection problem)."))

    # Short-paragraph dropping is proxy-markdown-only: on HTML-extracted text it
    # ate real content (plain short headings and their standalone lines) from the
    # classic full-text view — e.g. Android Authority's "Sofascore" h3.
    merged = _merge_texts(page_texts, drop_short_paragraphs=used_proxy_text)
    merged = _postprocess_extracted_text(merged, extraction_url)
    # Guard against gate text that slipped through extraction (e.g. a short verification body).
    if merged and len(merged) < _BOT_INTERSTITIAL_MAX_BODY_LEN and _looks_like_bot_interstitial(merged):
        raise ExtractionError(_blocked_interstitial_message(extraction_url))
    # Guard against pages with no article body (video-only/index pages): extraction "succeeds"
    # but yields only the page's navigation or related-story headlines, which would be shown
    # (and read aloud) as if they were the story. Raising lets callers fall back to feed content.
    if merged and _looks_like_link_list(merged):
        raise ExtractionError(_link_list_only_message())
    # Guard against a hard-paywall stub (headline + byline + "Subscribe to unlock"): let the
    # caller fall back to feed content instead of presenting the subscribe nag as the article.
    if merged and _looks_like_paywall_stub(merged):
        raise ExtractionError(_paywall_message())
    if not merged:
        raise ExtractionError(_("Downloaded page, but could not extract readable text (empty result)."))
    # Metered preview: the text above is only the free excerpt, so say why it stops
    # instead of letting the story trail off mid-report.
    if metered_preview:
        merged = merged.rstrip() + "\n\n" + metered_preview_notice()

    return FullArticle(url=url, title=title or "", author=author or "", text=merged)


def extract_from_html(html: str, source_url: str = "", title: str = "", author: str = "") -> Optional[FullArticle]:
    """
    Extract readable text from HTML already available in the feed item (fallback when no webpage URL exists).
    """
    html = (html or "").strip()
    if not html:
        return None
    text = _extract_text_any(html, source_url or "")
    text = _postprocess_extracted_text(text, source_url or "")
    if not text:
        return None

    # Prefer metadata extracted from HTML if present.
    t2, a2 = _extract_title_author_from_meta(html, source_url or "")
    final_title = (title or t2 or "").strip()
    final_author = (author or a2 or "").strip()

    return FullArticle(url=source_url or "", title=final_title, author=final_author, text=text)


def render_full_article(
    url: str,
    *,
    fallback_html: str = "",
    fallback_title: str = "",
    fallback_author: str = "",
    prefer_feed_content: bool = True,
    max_pages: int = 6,
    timeout: int = 20,
    metadata_sink=None,
    encoding: str = "",
) -> Optional[str]:
    """
    Render a full article into a single plain-text string (Title/Author/Text).

    Behavior:
    - If url is missing or looks like media, try fallback_html (feed content) and return that.
    - If url extraction fails, try fallback_html; if still fails, raise ExtractionError.
    - ``metadata_sink`` is forwarded to extract_full_article (first fetched
      page's HTML, for structured-metadata enrichment); it never affects output.
    """
    url = (url or "").strip()

    def _render(art: FullArticle) -> str:
        parts: List[str] = []
        unknown = _("(unknown)")
        parts.append(_("Title:") + f" {art.title.strip() or unknown}")
        parts.append(_("Author:") + f" {art.author.strip() or unknown}")
        parts.append("")
        body = _postprocess_extracted_text(art.text or "", url)
        # One paragraph per line, no blank lines in between. Trafilatura (the
        # successful web extraction) already reads that way; JSON-LD bodies,
        # feed-content fallbacks and the site strippers that rebuild a body
        # from paragraphs used to hand the reader a blank line between every
        # paragraph, so a failed extraction doubled the number of lines a
        # screen-reader user had to arrow through. Runs last, after every
        # stripper has done its paragraph-shaped work.
        parts.append(utils.collapse_blank_lines(body))
        return (_normalize_whitespace("\n".join(parts)) + "\n")

    # No usable URL: fall back to feed content.
    if not url:
        art = extract_from_html(fallback_html, "", title=fallback_title, author=fallback_author)
        if art:
            return _render(art)
        return None

    # Feed-authored content remains the fastest/best source for enclosures. If
    # it is absent, try bounded embedded ID3 show notes before giving up.
    if _looks_like_media_url(url):
        art = extract_from_html(fallback_html, "", title=fallback_title, author=fallback_author)
        if not art:
            art = extract_full_article(url, max_pages=1, timeout=timeout)
        if art:
            if fallback_title and not art.title:
                art.title = fallback_title
            if fallback_author and not art.author:
                art.author = fallback_author
            return _render(art)
        return None

    # Optimization: prefer feed content for known sites or if it looks complete
    if prefer_feed_content and _should_prefer_feed_content(url, fallback_html):
        art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
        if art:
            return _render(art)

    # Try webpage extraction.
    extraction_error: Optional[ExtractionError] = None
    try:
        # Pass optional kwargs only when set: keeps compatibility with callers
        # (and tests) that substitute extract_full_article without them.
        extra_kwargs = {}
        if metadata_sink is not None:
            extra_kwargs["metadata_sink"] = metadata_sink
        if encoding:
            extra_kwargs["encoding"] = encoding
        art = extract_full_article(url, max_pages=max_pages, timeout=timeout, **extra_kwargs)
        if art:
            if fallback_title and not art.title:
                art.title = fallback_title
            if fallback_author and not art.author:
                art.author = fallback_author
            return _render(art)
    except ExtractionError as e:
        # Remember why so we can surface it if there's no usable feed fallback either.
        extraction_error = e
    except Exception as e:
        raise ExtractionError(str(e) or _("Unknown extraction error"))

    # If URL extraction returned None, try fallback content.
    art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
    if art:
        return _render(art)

    if extraction_error is not None:
        raise extraction_error
    raise ExtractionError(_("Could not extract full text from the webpage or from feed content."))


def _should_prefer_feed_content(url: str, html: str) -> bool:
    """Return True if we should use the feed content instead of scraping."""
    if not html:
        return False

    low = html.lower()
    if "unable to retrieve full-text content" in low:
        return False

    # Ning activity feeds often contain the only useful human-readable description/excerpt
    # (e.g. "posted a video", discussion reply text, etc.). Scraping the target page can
    # return generic profile/site boilerplate instead, especially for profile activity items.
    try:
        host = urlsplit(url).hostname or ""
        host = host.lower()
        if host.endswith(".ning.com") or host == "ning.com":
            # Most Ning RSS activity entries are HTML fragments (not full pages) containing
            # the only useful summary/reply text. If we scrape the linked page instead, we may
            # get profile/site boilerplate and lose the activity description entirely.
            if "<html" not in low and "<body" not in low:
                if low.count("<a ") >= 1 and any(
                    marker in low
                    for marker in (
                        "/forum/topics/",
                        "/xn/detail/",
                        "/members/",
                        "posted a ",
                        "posted blog posts",
                        "replied",
                        "updated their",
                        "commentid=",
                        "xg_source=activity",
                    )
                ):
                    return True
            if any(
                marker in low
                for marker in (
                    "xg_source=activity",
                    "feed-string",
                    "feed-story-title",
                    "feed-more",
                    "rich-excerpt",
                )
            ):
                return True
    except Exception:
        pass
    
    # 1. Known sites where scraping is slow/blocked but feed is good
    try:
        host = urlsplit(url).hostname
        if host:
            host = host.lower()
            if host == "wired.com" or host.endswith(".wired.com"):
                # Wired feeds are usually decent summaries or full text
                if len(html) > 300:
                    return True
            # These publishers expose a shortened webpage body while placing the
            # complete syndicated story/newsletter in RSS.
            if host == "fraservalleytoday.ca" or host.endswith(".fraservalleytoday.ca"):
                return len(html) > 500
            if host == "fvcurrent.com" or host.endswith(".fvcurrent.com"):
                return len(html) > 500
    except Exception:
        pass

    # 2. General heuristic: if the feed content is very long, it's likely full text.
    if len(html) > 2500:
        return True
    
    return False
