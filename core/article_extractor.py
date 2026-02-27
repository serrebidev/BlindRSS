"""
Full-text article extraction using trafilatura.

Goal:
- Given an article URL, extract clean text (no ads/boilerplate) plus title and author.
- Follow simple multi-page pagination (rel=next / next links) and merge text.
- Provide safe fallbacks for feed items without a webpage URL (e.g., podcast episodes).
"""

from __future__ import annotations

import json
import re
import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional, Tuple, List, Set
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from core import utils

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


def _normalize_whitespace(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
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


def _extract_json_ld_text(html: str) -> str:
    if not html:
        return ""
    soup = _parse_html_soup(html, context="json-ld")
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
        t = _normalize_whitespace(c)
        if t:
            cleaned.append(t)

    if not cleaned:
        return ""

    cleaned.sort(key=len, reverse=True)
    best = cleaned[0]
    if len(best) < _JSON_LD_MIN_TEXT_LEN:
        return ""
    return best


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
    t = re.sub(r"(?i)You’re\s+reading\s+9to5Mac\s*—\s*experts\s+who\s+break\s+news.*?(?:loop\.|channel)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Check\s+out\s+our\s+exclusive\s+stories,.*?(?:channel|loop\.)", "", t, flags=re.DOTALL)
    return t

def _strip_globalnews_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)^By\s+Staff\s+The\s+Canadian\s+Press", "", text, flags=re.MULTILINE)
    t = re.sub(r"(?i)^Posted\s+\w+\s+\d+,\s+\d+\s+\d+:\d+\s+[ap]m", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)^\d+\s+min\s+read", "", t, flags=re.MULTILINE)
    t = re.sub(r"(?i)If\s+you\s+get\s+Global\s+News\s+from\s+Instagram\s+or\s+Facebook.*?(?:connect\s+with\s+us\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Hide\s+message\s+barDescrease\s+article\s+font\s+size\s*Increase\s+article\s+font\s+size", "", t)
    return t

def _strip_aljazeera_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Published\s+On\s+\d+\s+\w+\s+\d+.*?(?:20\d\d)", "", text)
    t = re.sub(r"(?i)Click\s+here\s+to\s+share\s+on\s+social\s+media", "", t)
    t = re.sub(r"(?i)share\d+Save", "", t)
    return t

def _strip_bbc_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)ShareSave", "", text)
    return t

def _strip_canada_boilerplate(text: str) -> str:
    t = re.sub(r"(?i)Advertisement\s+\d+", "", text)
    t = re.sub(r"(?i)This\s+advertisement\s+has\s+not\s+loaded\s+yet.*?(?:continues\s+below\.)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Author\s+of\s+the\s+article:.*?(?:read)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Join\s+the\s+conversation", "", t)
    t = re.sub(r"(?i)Read\s+More.*?(?:Article\s+content)", "", t, flags=re.DOTALL)
    t = re.sub(r"(?i)Share\s+this\s+article\s+in\s+your\s+social\s+network", "", t)
    t = re.sub(r"(?i)Trending\s+Latest\s+National\s+Stories", "", t)
    return t

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
    elif "globalnews.ca" in netloc:
        t = _strip_globalnews_boilerplate(t)
    elif "aljazeera.com" in netloc:
        t = _strip_aljazeera_boilerplate(t)
    elif "bbc.com" in netloc or "bbc.co.uk" in netloc:
        t = _strip_bbc_boilerplate(t)
    elif "o.canada.com" in netloc or "canada.com" in netloc:
        t = _strip_canada_boilerplate(t)
    elif "castanet.net" in netloc:
        t = _strip_castanet_boilerplate(t)
    elif "bloomberg.com" in netloc:
        t = _strip_bloomberg_boilerplate(t)
    elif netloc.endswith(".ning.com") or netloc == "ning.com":
        t = _strip_ning_activity_noise(t)

    return _normalize_whitespace(t)


def _download_html(url: str, timeout: int = 20) -> Optional[str]:
    """Download a URL and return HTML as text."""
    if not url:
        return None

    def _looks_like_cloudflare_block(text: str) -> bool:
        if not text:
            return False
        low = text.lower()
        if "cloudflare" not in low:
            return False
        return ("attention required" in low or "just a moment" in low or "cf-browser-verification" in low)

    def _download_via_jina(target_url: str) -> Optional[str]:
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

    try:
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        r = utils.safe_requests_get(url, timeout=timeout, headers=headers, allow_redirects=True)
        if 200 <= r.status_code < 400:
            r.encoding = r.encoding or "utf-8"
            return r.text
        try:
            if r is not None and (r.status_code in (403, 503) or _looks_like_cloudflare_block(r.text or "")):
                alt = _download_via_jina(url)
                if alt:
                    return alt
        except Exception:
            pass
        return None
    except Exception:
        return None


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

    if not title:
        try:
            soup = BeautifulSoup(html, "html.parser")
            t = soup.find("title")
            if t and t.get_text(strip=True):
                title = t.get_text(strip=True)
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
        deduplicate=True,
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


def _extract_text_any(html: str, url: str = "") -> str:
    # 1. Try JSON-LD first (often high quality on major sites like Wired)
    json_txt = _extract_json_ld_text(html)
    
    # Optimization: if JSON-LD gave us a substantial article, skip expensive Trafilatura
    if json_txt and len(json_txt) > 1000:
        return _normalize_whitespace(json_txt)

    # 2. Try Trafilatura
    txt = _trafilatura_extract_text(html, url=url)

    if txt and json_txt:
        txt_norm = _normalize_whitespace(txt)
        json_norm = _normalize_whitespace(json_txt)
        # If JSON-LD is significantly longer, prefer it
        if len(json_norm) > len(txt_norm) * 1.1:
            return json_norm
        return txt_norm

    if json_txt:
        return _normalize_whitespace(json_txt)
    if txt:
        return _normalize_whitespace(txt)
    
    # 3. Last resort fallback
    txt = _soup_extract_text(html)
    return _normalize_whitespace(txt)


def _find_next_page(html: str, base_url: str) -> Optional[str]:
    """Return absolute next-page URL if present, else None."""
    if not html:
        return None

    try:
        # Wired.com specific optimization:
        # Wired articles are typically single-page. "Next" links usually point to the *next story*,
        # which we definitely do NOT want to append.
        try:
            host = urlsplit(base_url).hostname
            if host and (host == "wired.com" or host.endswith(".wired.com")):
                return None
            if host and (host == "ning.com" or host.endswith(".ning.com")):
                # Ning "next/older" controls frequently navigate activity/thread listings
                # rather than paginated continuation of a single article.
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
            
            # Avoid "Next Story", "Next Article" which are common on news sites
            if "next story" in text or "next article" in text:
                continue
                
            if (
                any(k in text for k in ("next", "older", "next page"))
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


def _merge_texts(texts: List[str]) -> str:
    """Merge multiple page texts while de-duplicating repeated blocks."""
    seen: Set[str] = set()
    out: List[str] = []

    for t in texts:
        t = (t or "").strip()
        if not t:
            continue

        # de-dupe paragraph by paragraph
        paras = [p.strip() for p in t.split("\n") if p.strip()]
        merged_paras: List[str] = []
        for p in paras:
            key = re.sub(r"\s+", " ", p).strip().lower()
            if len(key) < 25:
                continue
            if key in seen:
                continue
            seen.add(key)
            merged_paras.append(p)

        if merged_paras:
            out.append("\n".join(merged_paras))

    return _normalize_whitespace("\n\n".join(out))


def extract_full_article(url: str, max_pages: int = 6, timeout: int = 20) -> Optional[FullArticle]:
    """
    Extract full article text from a URL. Attempts to follow pagination for multi-page articles.

    Returns FullArticle or None on unsupported/empty.
    Raises ExtractionError for download/extraction failures that should be shown to the user.
    """
    url = (url or "").strip()
    if not url or _looks_like_media_url(url):
        return None
    if trafilatura is None:
        raise ExtractionError("trafilatura is not installed or failed to import. Reinstall requirements.")

    visited: Set[str] = set()
    page_texts: List[str] = []

    current = url
    title = ""
    author = ""

    downloaded_any = False

    for _ in range(max_pages):
        if not current or current in visited:
            break
        visited.add(current)

        html = _download_html(current, timeout=timeout)
        if not html:
            break
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
        raise ExtractionError("Download failed (site blocked, offline, or connection problem).")

    merged = _merge_texts(page_texts)
    merged = _postprocess_extracted_text(merged, url)
    if not merged:
        raise ExtractionError("Downloaded page, but could not extract readable text (empty result).")

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
) -> Optional[str]:
    """
    Render a full article into a single plain-text string (Title/Author/Text).

    Behavior:
    - If url is missing or looks like media, try fallback_html (feed content) and return that.
    - If url extraction fails, try fallback_html; if still fails, raise ExtractionError.
    """
    url = (url or "").strip()

    def _render(art: FullArticle) -> str:
        parts: List[str] = []
        parts.append(f"Title: {art.title.strip() or '(unknown)'}")
        parts.append(f"Author: {art.author.strip() or '(unknown)'}")
        parts.append("")
        body = _postprocess_extracted_text(art.text or "", url)
        parts.append(body.strip())
        return (_normalize_whitespace("\n".join(parts)) + "\n")

    # No usable URL: fall back to feed content.
    if not url or _looks_like_media_url(url):
        art = extract_from_html(fallback_html, "", title=fallback_title, author=fallback_author)
        if art:
            return _render(art)
        return None

    # Optimization: prefer feed content for known sites or if it looks complete
    if prefer_feed_content and _should_prefer_feed_content(url, fallback_html):
        art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
        if art:
            return _render(art)

    # Try webpage extraction.
    try:
        art = extract_full_article(url, max_pages=max_pages, timeout=timeout)
        if art:
            if fallback_title and not art.title:
                art.title = fallback_title
            if fallback_author and not art.author:
                art.author = fallback_author
            return _render(art)
    except ExtractionError:
        # fall through to fallback handling below
        pass
    except Exception as e:
        raise ExtractionError(str(e) or "Unknown extraction error")

    # If URL extraction returned None, try fallback content.
    art = extract_from_html(fallback_html, url, title=fallback_title, author=fallback_author)
    if art:
        return _render(art)

    raise ExtractionError("Could not extract full text from the webpage or from feed content.")


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
    except Exception:
        pass

    # 2. General heuristic: if the feed content is very long, it's likely full text.
    if len(html) > 2500:
        return True
    
    return False
