# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Embed-preserving article HTML cleaning for the opt-in rich reader.

The plain-text reader uses trafilatura, which deliberately strips everything
that is not prose — including the ``<iframe>`` video widgets and embedded
tweets a reader may want to open. The rich reader renders real HTML in an
accessible ``wx.html2.WebView`` instead, so this module produces a *sanitized
article-body fragment* that keeps prose, links, images, tables, and media
embeds while dropping page chrome (nav / sidebars / tickers / scripts / ads).

Design notes:
- We never render the live page. We isolate the main article node and sanitize
  its subtree, so the site's own chrome scripts (tickers, notification prompts)
  never come along — only the embeds that live *inside* the article do.
- The WebView renders a data page with no base URL, so every ``href``/``src``
  is absolutized against the article URL or relative assets would break.
- Content is injected via ``innerHTML`` in the WebView, which does not execute
  injected ``<script>`` tags. YouTube/Vimeo ``<iframe>`` embeds still load;
  script-hydrated widgets (tweets) degrade to a clickable permalink, which is
  fine — link clicks are diverted to the system browser.
"""

from __future__ import annotations

import html as _html
import re
import time
from typing import Optional
from urllib.parse import quote, urljoin, urlsplit

from bs4 import BeautifulSoup

from core import article_lang
from core import utils


# Tags whose *content* is worth keeping in a cleaned article body.
_ALLOWED_TAGS = {
    "p", "br", "hr", "span", "div", "section", "article", "main",
    "figure", "figcaption", "picture",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd",
    "blockquote", "q", "cite", "pre", "code", "em", "strong", "b", "i",
    "u", "s", "sub", "sup", "mark", "small", "abbr", "time",
    "a", "img", "source",
    "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption",
    "colgroup", "col",
    "iframe", "video", "audio", "track",
}

# Tags dropped entirely, contents and all: scripts, forms, and the semantic
# chrome that carries navigation / tickers / share bars.
_DROP_TAGS = {
    "script", "style", "noscript", "template", "svg", "canvas",
    "form", "input", "button", "select", "textarea", "label",
    "nav", "aside", "header", "footer", "object", "embed", "ins",
    "link", "meta", "base", "dialog",
}

# Short blocks whose *text* is a stock affiliate/commission disclosure or
# subscribe nag. Many sites (e.g. Android Authority) ship these with hashed CSS
# class names, so class matching can't catch them — the wording is the stable
# signal. Only applied to short blocks so real prose that mentions commissions
# is never removed.
_BOILERPLATE_TEXT_RE = re.compile(
    r"(?i)("
    # Affiliate / commission disclosures
    r"affiliate links?\b.{0,80}\bcommission"
    r"|may earn\b.{0,40}\bcommission"
    r"|earns?\s+(?:us\s+)?an?\s+(?:small\s+)?commission"
    r"|we may (?:earn|receive|get)\b.{0,40}(?:commission|compensat)"
    r"|contains? affiliate links?"
    r"|this (?:post|article|page)\b.{0,30}\baffiliate links?"
    # Subscribe / paywall / login / newsletter nags
    r"|sign up (?:for|to)\b.{0,40}\bnewsletter"
    r"|subscribe (?:to|today|now|for)\b"
    r"|unlimited access\b"
    r"|subscriber[- ](?:only|content|exclusive)"
    r"|best-in-class reporting"
    r"|delivered (?:to|straight to) your inbox"
    r"|get (?:the|our)\b.{0,30}\bnewsletter"
    r"|join (?:our|the)\b.{0,30}\bnewsletter"
    r"|(?:please )?log ?in to (?:bookmark|read|continue|save)"
    r"|create (?:a )?free account"
    r"|already a (?:subscriber|member)"
    r"|open this photo in gallery"
    r"|follow us on\b.{0,20}\b(?:google|discover|flipboard|twitter|facebook|instagram|threads|youtube|tiktok|linkedin|mastodon|bluesky|whatsapp|telegram)"
    r"|add us as (?:a )?preferred source"
    # Community / comment-policy footer (Valnet network: Android Authority,
    # Android Police, How-To Geek, etc. — "Thank you for being part of our
    # community. Read our Comment Policy before posting.")
    r"|thank you for being part of our community"
    r"|read our comment policy"
    r"|comment policy before posting"
    r")"
)
# Short label-only widget headers ("ZDNET Recommends", "Related stories",
# "Read more", "Most popular"). Matched against the whole (short) block.
_WIDGET_HEADER_RE = re.compile(
    r"(?i)^\W*("
    r"(?:zdnet|editor'?s?|our)\s+(?:recommends?|picks?|choice)"
    r"|recommended (?:stories|reading|for you|videos?)"
    r"|(?:related|more|popular|trending|latest)\s+(?:stories|articles|reading|coverage|posts?|news|videos?)"
    r"|read (?:more|next|also)"
    r"|(?:up|coming) next"
    r"|you (?:might|may) (?:also )?like"
    r"|most (?:popular|read)"
    r"|trending now"
    r"|(?:see|show) more"
    r"|advertisement"
    r"|sponsored( content| links?)?"
    r")\W*$"
)
_BOILERPLATE_MAX_LEN = 240

# Byline / timestamp leaf lines ("By", "Jul 15, 2026 4:14 AM ET", "Updated:").
# The reader shows author/date in its own header, so these are redundant.
_BYLINE_RE = re.compile(
    r"(?i)(?:^by$|^by\s|\b\d{1,2}:\d{2}\s*(?:a\.?m\.?|p\.?m\.?)\b"
    r"|\b\d{1,2}:\d{2}\b\s*(?:et|est|edt|pt|pst|pdt|ct|cst|mt|gmt|utc)\b"
    r"|^(?:updated|published|posted|last updated)\b\s*:?)"
)

# Elements whose class/id clearly marks page furniture rather than article body.
_CHROME_RE = re.compile(
    r"(?i)(?:^|[-_ ])(?:sidebar|advert|advertisement|\bads?\b|promo|newsletter|"
    r"subscribe|signup|related|recommend|trending|sharethis|share-|social|"
    r"comments?|disqus|cookie|consent|ticker|breaking-?bar|popup|modal|"
    # `meter` targets paywall meter widgets, but must not swallow NYT's
    # `meteredContent` wrapper — that container IS the article body.
    r"paywall|meter(?!ed)|taboola|outbrain|more-from|read-?more|back-to-top|"
    r"breadcrumb|post-?meta|entry-?meta|post-?tags?|tags?-list|tag-?cloud|"
    r"cat-?links|post-?categories|author-?bio|author-?box|byline|most-?popular|"
    r"up-?next|read-?next|editors?-?picks?|sponsor|partner|follow-?us|"
    r"newsletter-?signup|email-?signup|jump-?link|toc|inline-?promo|"
    r"visually-?hidden|sr-?only|screen-?reader|toggletip|popover|tooltip|"
    r"discover|preferred-?source|bookmark|save-?story|gallery-?caption)"
)

# Attributes kept, per tag. Everything else (on* handlers, style, class, id,
# data-*, tracking params) is dropped.
_ATTR_KEEP = {
    "a": {"href", "title"},
    "img": {"src", "srcset", "alt", "title"},
    "source": {"src", "srcset", "type", "media"},
    "iframe": {"src", "title", "allow", "allowfullscreen", "width", "height"},
    "video": {"src", "poster", "controls", "width", "height"},
    "audio": {"src", "controls"},
    "track": {"src", "kind", "srclang", "label", "default"},
    "time": {"datetime"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan"},
}
_URL_ATTRS = {"href", "src", "poster"}

# Zero-width characters some publishers (e.g. Reuters) sprinkle between words to
# frustrate scraping — invisible, never real content, stripped from the body.
_ZERO_WIDTH_RE = re.compile("[​‌‍⁠﻿]")


def _text_len(node) -> int:
    try:
        return len(node.get_text(" ", strip=True))
    except Exception:
        return 0


def _norm(text: str) -> str:
    """Lowercase, collapse to alphanumerics — for robust text-overlap matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def _has_content_image(tag) -> bool:
    """True if ``tag`` contains a real content image (not a decorative SVG/icon
    used by share/follow/promo widgets, which often carry misleading alt text)."""
    for img in tag.find_all("img"):
        if not str(img.get("alt") or "").strip():
            continue
        src = str(img.get("src") or img.get("data-src") or "").lower()
        if ".svg" in src or src.startswith("data:"):
            continue
        return True
    return False


def _only_whitespace(siblings) -> bool:
    """True when every sibling in ``siblings`` is whitespace-only text.

    Used to spot a ``<br>`` at the very start or end of its container, where it
    adds an empty line and nothing else.
    """
    for sib in siblings:
        if getattr(sib, "name", None) is not None:
            return False
        if str(sib).strip():
            return False
    return True


def _has_prose_child(tag) -> bool:
    """True if ``tag`` wraps a block-level prose element (so it's a container,
    not a leaf we can safely drop wholesale)."""
    return tag.find(["p", "h1", "h2", "h3", "ul", "ol", "blockquote", "table", "figure"]) is not None


def _article_keep_text(html: str, url: str) -> str:
    """Normalized recall-mode trafilatura extraction — the article's real text.

    Used as ground truth to prune blocks (tags, related widgets, newsletter
    blurbs) the extractor excluded but that live inside the article node. Recall
    mode is deliberately generous so real prose is never pruned by mistake.
    Returns '' when trafilatura is unavailable or extracts nothing.
    """
    try:
        import trafilatura
    except Exception:
        return ""
    try:
        txt = trafilatura.extract(
            html,
            url=url or None,
            favor_recall=True,
            include_links=False,  # links inject "(url)" tokens that break matching
            include_tables=True,
            include_comments=False,
            output_format="txt",
        )
    except Exception:
        return ""
    return _norm(txt or "")


def _normalize_media_url(value: str) -> str:
    """Turn a known player/embed URL into a page a browser can open directly."""
    value = str(value or "").strip()
    if value.startswith("//"):
        value = "https:" + value
    try:
        parts = urlsplit(value)
    except Exception:
        return value
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        m = re.match(r"/embed/([A-Za-z0-9_-]{6,})", path)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
    if host.endswith("player.vimeo.com"):
        m = re.match(r"/video/(\d+)", path)
        if m:
            return f"https://vimeo.com/{m.group(1)}"
    return value


def _absolutize(value: str, base_url: str) -> str:
    value = str(value or "").strip()
    if not value or value.startswith(("data:", "mailto:", "tel:", "#")):
        return value
    if value.startswith("//"):
        return "https:" + value
    if base_url and not urlsplit(value).scheme:
        try:
            return urljoin(base_url, value)
        except Exception:
            return value
    return value


def _absolutize_srcset(value: str, base_url: str) -> str:
    parts = []
    for chunk in str(value or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        bits = chunk.split(None, 1)
        url = _absolutize(bits[0], base_url)
        parts.append(url + (f" {bits[1]}" if len(bits) > 1 else ""))
    return ", ".join(parts)


# --- Social-media embeds -------------------------------------------------
#
# Platform embeds (X/Twitter, Facebook, Instagram, TikTok, Bluesky, Threads,
# Mastodon) ship as a <blockquote>/<div> plus a widget script that hydrates it.
# The WebView injects our HTML via innerHTML, which never runs those scripts, so
# each is converted here to the platform's canonical <iframe> embed URL (renders
# the real post inline) — or, when an iframe URL can't be built, to a clickable
# permalink so the reader can still open it in the browser.

_RE_TWITTER = re.compile(r"(?:twitter\.com|x\.com)/[^/\s]+/status(?:es)?/(\d+)", re.I)
_RE_INSTAGRAM = re.compile(r"instagram\.com/(?:p|reel|tv)/([A-Za-z0-9_-]+)", re.I)
_RE_TIKTOK = re.compile(r"tiktok\.com/@[^/\s]+/video/(\d+)", re.I)
_RE_TIKTOK_ID = re.compile(r"(\d{6,})")
_RE_BSKY_ATURI = re.compile(r"(did:[^/\s]+)/app\.bsky\.feed\.post/([A-Za-z0-9]+)", re.I)
_RE_BSKY_URL = re.compile(r"bsky\.app/profile/([^/\s]+)/post/([A-Za-z0-9]+)", re.I)
_RE_THREADS = re.compile(r"threads\.(?:net|com)/(@[^/\s]+/post/[A-Za-z0-9_-]+)", re.I)


def _first_href(el):
    for a in el.find_all("a", href=True):
        href = str(a.get("href") or "").strip()
        if href and href.lower().startswith(("http://", "https://")):
            return href
    return ""


def _social_embed_for(el, base_url: str):
    """Return (iframe_src, permalink, platform_label) for a social embed, else None."""
    classes = " ".join(el.get("class") or []).lower()
    # Gather candidate URLs from data attributes and inner links.
    data_href = ""
    for attr in ("data-href", "data-instgrm-permalink", "data-embed-url", "cite", "data-url"):
        v = str(el.get(attr) or "").strip()
        if v:
            data_href = _absolutize(v, base_url)
            break
    href = data_href or _absolutize(_first_href(el), base_url)
    at_uri = str(el.get("data-bluesky-uri") or "")
    hay = f"{classes} {href} {at_uri} {el.get('data-embed-url','')}"

    # Twitter / X
    m = _RE_TWITTER.search(hay)
    if "twitter-tweet" in classes or "twitter-video" in classes or m:
        if m:
            return (f"https://platform.twitter.com/embed/Tweet.html?id={m.group(1)}", href, "X")
        return ("", href, "X")

    # Bluesky
    if "bluesky-embed" in classes or "bsky.app" in hay or at_uri:
        m = _RE_BSKY_ATURI.search(at_uri) or _RE_BSKY_ATURI.search(hay)
        if m:
            return (
                f"https://embed.bsky.app/embed/{m.group(1)}/app.bsky.feed.post/{m.group(2)}",
                href, "Bluesky",
            )
        mu = _RE_BSKY_URL.search(hay)
        if mu and mu.group(1).startswith("did:"):
            return (
                f"https://embed.bsky.app/embed/{mu.group(1)}/app.bsky.feed.post/{mu.group(2)}",
                href, "Bluesky",
            )
        return ("", href, "Bluesky")

    # Instagram
    m = _RE_INSTAGRAM.search(hay)
    if "instagram-media" in classes or m:
        if m:
            return (f"https://www.instagram.com/p/{m.group(1)}/embed", href, "Instagram")
        return ("", href, "Instagram")

    # TikTok
    m = _RE_TIKTOK.search(hay)
    if "tiktok-embed" in classes or m:
        vid = m.group(1) if m else str(el.get("data-video-id") or "").strip()
        if not vid:
            mt = _RE_TIKTOK_ID.search(hay)
            vid = mt.group(1) if mt else ""
        if vid:
            return (f"https://www.tiktok.com/embed/v2/{vid}", href, "TikTok")
        return ("", href, "TikTok")

    # Facebook
    if "fb-post" in classes or "fb-video" in classes or "facebook.com/plugins" in hay:
        if href:
            src = (
                "https://www.facebook.com/plugins/post.php?href="
                + quote(href, safe="") + "&show_text=true"
            )
            return (src, href, "Facebook")
        return ("", href, "Facebook")

    # Threads
    m = _RE_THREADS.search(hay)
    if "text-post-media" in classes or "threads-embed" in classes or m:
        if m:
            return (f"https://www.threads.net/{m.group(1)}/embed", href, "Threads")
        return ("", href, "Threads")

    # Mastodon (usually already an iframe; blockquote form carries data-embed-url)
    if "mastodon-embed" in classes:
        embed = str(el.get("data-embed-url") or "").strip()
        if embed:
            return (_absolutize(embed, base_url), href, "Mastodon")
        return ("", href, "Mastodon")

    return None


def _convert_social_embeds(soup, node, base_url: str) -> None:
    """Rewrite known social-embed blockquotes/divs in ``node`` into iframes/links."""
    for el in list(node.find_all(["blockquote", "div"])):
        if getattr(el, "decomposed", False):
            continue
        info = _social_embed_for(el, base_url)
        if not info:
            continue
        iframe_src, permalink, label = info
        if iframe_src:
            new = soup.new_tag("iframe", src=iframe_src)
            new["title"] = f"{label} post"
            new["loading"] = "lazy"
            new["allowfullscreen"] = "true"
        elif permalink:
            new = soup.new_tag("p")
            quoted = el.get_text(" ", strip=True)
            if quoted:
                new.append(soup.new_string(quoted + " — "))
            a = soup.new_tag("a", href=permalink)
            a.string = f"View this post on {label}"
            new.append(a)
        else:
            continue
        el.replace_with(new)


def _pick_main_node(soup: BeautifulSoup):
    """Return the best guess at the main article node, or the body.

    Semantic elements are tried first, then the content-body class names common
    to blog/CMS templates (WordPress ``entry-content``, Simon Willison's blog
    ``entry``, etc.). Isolating that node keeps sibling chrome — "Recent
    articles" lists, tag boxes, sponsor promos — out of the cleaned body on
    sites that ship no ``<article>``/``<main>`` element.
    """
    for selector in (
        "article", "main", "[role=main]", "[itemprop=articleBody]",
        ".entry-content", ".post-content", ".article-content", ".article-body",
        ".entry-body", ".story-body", ".post-body", ".entry",
    ):
        try:
            node = soup.select_one(selector)
        except Exception:
            node = None
        if node is not None and _text_len(node) > 200:
            return node
    return soup.body or soup


def _harvest_embeds_html(node) -> list:
    """Return the sanitized HTML of media embeds inside ``node``, in order."""
    out = []
    for tag in node.find_all(["iframe", "video", "audio"]):
        if getattr(tag, "decomposed", False):
            continue
        out.append(str(tag))
    return out


# socast / Pattison-portals radio-CMS: the story body is split across a lead in
# div.wpb-content-wrapper and a continuation in a second <article class="mainArticle">,
# with related-post/newsletter/ad widgets interleaved. _pick_main_node grabs only the
# lead article, and the trafilatura prune (keep_text) then sees only the lead and would
# strip the continuation. _socast_reconstruct merges both body containers (keeping the
# header image), and clean_article_html disables the prune for the merged node.
_SOCAST_JUNK_TOKENS = (
    "items-wrapper", "bnl-pp-happening", "bnl-info", "bnl-title", "bnl-content",
    "pp-more-wrapper", "wpb_raw", "sc-author", "entry-footer", "entry-meta",
    "report_an_error", "highlight-text", "scwidgetcontainer", "sc-item-detail",
    "parallax-breakout", "pp-btn-container",
)


def _is_forum_thread_host(url: str) -> bool:
    from core import article_extractor as ae  # lazy: avoid import cycle at load

    return ae._is_forum_thread_host(url)


def _forum_reconstruct(soup, url: str):
    """Rebuild a supported forum thread as one node: a heading + body per post.

    A thread is a flat list of sibling ``div.post`` blocks, so the generic main-node
    pick lands on a single post and the rest of the conversation is lost — on a
    20-reply audiogames.net topic the reader showed only the last poster's signature.
    Drupal and Invision likewise keep replies as sibling articles.
    Each post's number/byline/timestamp becomes an ``<h2>`` so a screen reader can
    move post to post with the heading key, which a flat wall of replies does not
    allow. Returns None when the page has no recognizable posts, so the generic path
    still runs for forum indexes and error pages.
    """
    from core import article_extractor as ae  # lazy: avoid import cycle at load

    layout = ae._forum_layout_of(soup)
    if layout is None:
        return None
    container = soup.new_tag("article")
    for header, body in ae._forum_blocks(soup, layout):
        if not body.get_text(strip=True):
            continue
        if header:
            heading = soup.new_tag("h2")
            heading.string = header
            container.append(heading)
        container.append(body.extract())
    return container if container.find(True) is not None else None


def _looks_socast(html: str) -> bool:
    if not html:
        return False
    low = html.lower()
    if "socastsrm.com" in low:
        return True
    return (
        "wpb-content-wrapper" in low
        and "mainarticle" in low
        and "sc-content" in low
    )


def _strip_socast_junk(node) -> None:
    for el in node.find_all(True):
        if getattr(el, "decomposed", False):
            continue
        ident = (" ".join(el.get("class") or []) + " " + str(el.get("id") or "")).lower()
        if ident.strip() and any(tok in ident for tok in _SOCAST_JUNK_TOKENS):
            el.decompose()


def _socast_reconstruct(soup, url: str):
    """Merge a socast split story body into one node, junk removed.

    The body is split across *multiple* <article class="mainArticle"> elements
    (lead — with the header image/caption — plus one or more continuations). Merge
    them all, plus any lead wrapper that sits outside a mainArticle (a theme variant
    where the lead lives in a plain content article). Dedup and drop nested containers
    so nothing is included twice.
    """
    candidates = []
    # A lead wrapper whose surrounding article is NOT a mainArticle (variant layout).
    for lead in soup.select("div.wpb-content-wrapper"):
        if lead.find_parent("article", class_="mainArticle") is not None:
            continue
        candidates.append(lead.find_parent("article") or lead)
    candidates.extend(soup.select("article.mainArticle"))

    parts = []
    for el in candidates:
        if any(el is kept or el in kept.descendants for kept in parts):
            continue  # already covered by an ancestor we kept
        parts = [kept for kept in parts if kept not in el.descendants]  # drop nested
        parts.append(el)
    if not parts:
        return None

    container = soup.new_tag("article")
    for part in parts:
        container.append(part.extract())
    _strip_socast_junk(container)
    if _text_len(container) < 200:
        return None
    return container


def clean_article_html(html: str, url: str = "", *, use_traf_prune: bool = True) -> str:
    """Return a sanitized article-body HTML fragment, or '' if none is usable.

    Keeps prose, links, images, tables, and media embeds; drops page chrome,
    scripts, ad/ticker widgets, and (when ``use_traf_prune``) any block the
    trafilatura extractor judged to be outside the article body. Absolutizes
    URLs against ``url``.
    """
    if not html:
        return ""
    try:
        soup = BeautifulSoup(str(html), "html.parser")
    except Exception:
        return ""

    # Some layouts have no single node that holds the whole body, so it is rebuilt
    # before the generic pick: socast/Pattison-portals split a story across two
    # containers, and a forum thread is a flat list of sibling posts. The trafilatura
    # prune is disabled for a rebuilt body — its keep_text reflects only the part the
    # extractor picked (socast's short lead, or one post of a thread), so pruning
    # against it would strip everything the reconstruction just recovered.
    reconstructed = False
    node = None
    for detect, rebuild in (
        (_looks_socast(str(html)), _socast_reconstruct),
        (_is_forum_thread_host(url), _forum_reconstruct),
    ):
        if not detect:
            continue
        try:
            node = rebuild(soup, url)
        except Exception:
            node = None
        if node is not None:
            reconstructed = True
            break
    if node is None:
        node = _pick_main_node(soup)
    if node is None:
        return ""

    # Ground-truth article text (recall mode). Computed on the full page before
    # we mutate the node, and reused both to prune non-article blocks and to
    # detect a broken main-node pick (paywall stub) below.
    keep_text = (
        "" if reconstructed else (_article_keep_text(str(html), url) if use_traf_prune else "")
    )

    # Turn script-hydrated social embeds into iframes/permalinks first, so the
    # generic sanitize below keeps the resulting <iframe>/<a> nodes.
    try:
        _convert_social_embeds(soup, node, url)
    except Exception:
        pass

    # Category/tag/breadcrumb links (WordPress rel="tag"/"category tag").
    for a in node.find_all("a"):
        if getattr(a, "decomposed", False):
            continue
        rel = a.get("rel") or []
        rel = rel if isinstance(rel, (list, tuple)) else [rel]
        if any(str(r).lower() in ("tag", "category") for r in rel):
            a.decompose()

    # Drop chrome/script tags outright.
    for tag in node.find_all(_DROP_TAGS | _ALLOWED_TAGS):
        # Decomposing a parent detaches children that are still in this list.
        if getattr(tag, "decomposed", False):
            continue
        name = tag.name or ""
        if name in _DROP_TAGS:
            tag.decompose()
            continue
        # Class/id furniture (kept-tag containers like <div class="related">).
        # Never drop a container that holds a real media embed — a wrapper like
        # <div class="social-embed"> would otherwise take its iframe with it.
        ident = " ".join(
            filter(None, [
                " ".join(tag.get("class") or []),
                str(tag.get("id") or ""),
            ])
        )
        if ident and _CHROME_RE.search(ident):
            if tag.find(["iframe", "video", "audio"]):
                continue
            tag.decompose()

    # Stock affiliate/subscribe disclosures and label-only widget headers (short
    # blocks, matched by text because their class names are often hashed).
    for tag in node.find_all(["p", "div", "aside", "small", "figcaption", "span", "section", "h2", "h3", "h4"]):
        if getattr(tag, "decomposed", False):
            continue
        if tag.find(["iframe", "video", "audio"]) or _has_content_image(tag):
            continue
        txt = tag.get_text(" ", strip=True)
        if not txt or len(txt) > _BOILERPLATE_MAX_LEN:
            continue
        if _BOILERPLATE_TEXT_RE.search(txt) or (len(txt) <= 70 and _WIDGET_HEADER_RE.match(txt)):
            tag.decompose()

    # Trafilatura-guided prune: drop prose blocks whose text the extractor
    # excluded from the article (tags, related-story blurbs, promos). Only prose
    # containers are considered — media is kept by the media check, and headings
    # are left for navigation. Skipped when the ground-truth text is too small to
    # trust (extractor underperformed) so real content is never wrongly removed.
    if keep_text and len(keep_text) >= 400:
        for tag in node.find_all(["p", "li", "blockquote", "dd"]):
            if getattr(tag, "decomposed", False):
                continue
            if tag.find(["iframe", "video", "audio", "img"]):
                continue
            probe = _norm(tag.get_text(" ", strip=True))
            if len(probe) < 25:
                continue
            if probe[:60] not in keep_text:
                tag.decompose()

        # Pure link clusters (breadcrumbs, tag rows, related lists, follow/share
        # widgets): a block that is essentially only links, whose text the
        # extractor excluded. Icon images (no alt) are allowed here so a
        # "Follow us"/"preferred source" promo built from icon links is caught.
        for tag in node.find_all(["nav", "div", "ul", "ol", "section", "header", "p"]):
            if getattr(tag, "decomposed", False):
                continue
            if tag.find(["iframe", "video", "audio"]) or _has_content_image(tag):
                continue
            anchors = tag.find_all("a")
            if len(anchors) < 2:
                continue
            full = _norm(tag.get_text(" ", strip=True))
            link_txt = _norm(" ".join(a.get_text(" ", strip=True) for a in anchors))
            if not full or full[:60] in keep_text:
                continue
            # Almost all of the block's text lives inside its links -> it's nav,
            # not prose (a real paragraph has ample text outside its links).
            if len(full) - len(link_txt) <= 15:
                tag.decompose()

        # Short non-prose blocks the extractor excluded: byline fragments, date
        # lines, photo credits, and hashed-class promo widgets that class rules
        # can't target (e.g. Android Authority's obfuscated markup). Guarded to
        # leaf blocks only, so real prose containers are never removed.
        for tag in node.find_all(["p", "div", "span", "figcaption", "small", "li", "h4", "h5", "h6"]):
            if getattr(tag, "decomposed", False):
                continue
            if tag.find(["iframe", "video", "audio"]) or _has_content_image(tag):
                continue
            if _has_prose_child(tag):
                continue
            probe = _norm(tag.get_text(" ", strip=True))
            if len(probe) < 3 or len(probe) > 120:
                continue
            if probe[:60] not in keep_text:
                tag.decompose()

    # Separator/bullet-only leaves (e.g. <div>•</div> byline dividers) that
    # render as blank bullet lines. Runs regardless of the extractor.
    for tag in node.find_all(["p", "div", "span", "li"]):
        if getattr(tag, "decomposed", False):
            continue
        if tag.find(["iframe", "video", "audio", "img", "a"]):
            continue
        raw = tag.get_text(strip=True)
        if raw and not _norm(raw):  # only punctuation/bullets/symbols
            tag.decompose()

    # Byline / timestamp leaf lines, redundant with the reader's own header.
    for tag in node.find_all(["p", "div", "span", "time", "small", "li"]):
        if getattr(tag, "decomposed", False):
            continue
        if tag.find(["iframe", "video", "audio"]) or _has_content_image(tag):
            continue
        if _has_prose_child(tag):
            continue
        raw = tag.get_text(" ", strip=True)
        if raw and len(raw) <= 120 and _BYLINE_RE.search(raw):
            tag.decompose()

    # Normalize media embeds and sanitize attributes on everything that remains.
    for tag in list(node.find_all(True)):
        if getattr(tag, "decomposed", False):
            continue
        name = tag.name or ""
        if name not in _ALLOWED_TAGS:
            # Unknown/disallowed inline wrapper: unwrap (keep its children/text).
            tag.unwrap()
            continue
        if name in ("iframe", "video", "audio", "source"):
            src = tag.get("src") or tag.get("data-src") or ""
            if src:
                tag["src"] = _normalize_media_url(_absolutize(str(src), url))
        if name == "img":
            src = tag.get("src") or tag.get("data-src") or tag.get("data-lazy-src") or ""
            if src:
                tag["src"] = _absolutize(str(src), url)
        keep = _ATTR_KEEP.get(name, set())
        for attr in list(tag.attrs.keys()):
            if attr not in keep:
                del tag[attr]
                continue
            if attr in _URL_ATTRS:
                tag[attr] = _absolutize(str(tag.get(attr) or ""), url)
            elif attr == "srcset":
                tag[attr] = _absolutize_srcset(str(tag.get(attr) or ""), url)

    # Blank lines, HTML edition. Feeds routinely separate paragraphs with
    # <br><br> instead of <p>, and a leading/trailing <br> is left over
    # whenever chrome around it was removed. Each of those renders as an empty
    # line the screen reader stops on -- the rich-view counterpart of the blank
    # lines the plain-text reader strips. Runs of <br> collapse to one (which
    # still breaks the line); edge ones go entirely.
    for br in node.find_all("br"):
        if getattr(br, "decomposed", False):
            continue
        sib = br.next_sibling
        while sib is not None:
            if getattr(sib, "name", None) == "br":
                nxt = sib.next_sibling
                sib.decompose()
                sib = nxt
                continue
            if getattr(sib, "name", None) is None and not str(sib).strip():
                sib = sib.next_sibling
                continue
            break
    for br in node.find_all("br"):
        if getattr(br, "decomposed", False):
            continue
        if _only_whitespace(br.previous_siblings) or _only_whitespace(br.next_siblings):
            br.decompose()

    # Drop empty media-less containers left behind by chrome removal (incl. now-
    # empty lists so no blank bullet rows remain).
    for tag in node.find_all(["p", "div", "span", "section", "figure", "li", "ul", "ol", "dl"]):
        if getattr(tag, "decomposed", False):
            continue
        if tag.find(["img", "iframe", "video", "audio", "a", "source"]):
            continue
        if not tag.get_text(strip=True):
            tag.decompose()

    body = node.decode_contents() if hasattr(node, "decode_contents") else str(node)
    # Strip zero-width characters (Reuters and others inject them between words as
    # an anti-scraping measure): invisible, never meaningful content, and a source
    # of screen-reader stumbles. Safe on the serialized fragment — they never occur
    # meaningfully in tag/attribute syntax.
    body = _ZERO_WIDTH_RE.sub("", body).strip()

    # Paywall / mis-picked node: when the sanitized body has far less text than
    # the extractor found (e.g. Wired's paywall stub), rebuild the body from the
    # extractor's text and append any media embeds we salvaged from the node.
    # Gated on a substantial extraction so a legitimately short article (whose
    # recall-mode text merely swept in some chrome) never triggers a rebuild.
    if keep_text and len(keep_text) >= 1200:
        body_len = len(_norm(BeautifulSoup(body, "html.parser").get_text(" ", strip=True)))
        if body_len < 0.4 * len(keep_text):
            rebuilt = _traf_body_html(str(html), url)
            if rebuilt:
                embeds = "".join(_harvest_embeds_html(node))
                body = rebuilt + embeds

    # Guard against a result that is only whitespace/markup with no real content.
    if not BeautifulSoup(body, "html.parser").get_text(strip=True) and "<iframe" not in body:
        return ""
    return body


def _traf_body_html(html: str, url: str) -> str:
    """Build an HTML body from trafilatura's extracted text (paragraphs)."""
    try:
        import trafilatura
    except Exception:
        return ""
    try:
        txt = trafilatura.extract(
            html,
            url=url or None,
            favor_recall=True,
            include_links=False,
            include_tables=True,
            include_comments=False,
            output_format="txt",
        )
    except Exception:
        txt = ""
    txt = (txt or "").strip()
    if not txt:
        return ""
    # trafilatura's txt output puts each block (paragraph, heading, list item) on
    # its own line separated by a SINGLE newline — not a blank line — so split on
    # any run of newlines. Splitting on \n{2,} collapsed the whole article into
    # one giant <p> on sites that hit this rebuild path (e.g. Wired's paywall stub).
    return "".join(
        f"<p>{_html.escape(block.strip())}</p>"
        for block in re.split(r"\n+", txt)
        if block.strip()
    )


def _feed_fallback_html(fallback_html: str, url: str) -> str:
    # Feed content is already a short description, not a full page: skip the
    # trafilatura prune (extra fetch-free extraction that would rarely help).
    cleaned = clean_article_html(fallback_html, url, use_traf_prune=False)
    if cleaned:
        return cleaned
    # Last resort: escape plain text into a single paragraph.
    text = utils.html_to_text(fallback_html) if fallback_html else ""
    text = (text or "").strip()
    if not text:
        return ""
    paras = "".join(
        f"<p>{_html.escape(block)}</p>"
        for block in re.split(r"\n{2,}", text)
        if block.strip()
    )
    return paras


_YOUTUBE_ACCESSIBLE_CHUNK_CHARS = 16_384


def _accessible_text_chunks(text: str, limit: int = _YOUTUBE_ACCESSIBLE_CHUNK_CHARS) -> list[str]:
    """Split a large text leaf at readable boundaries without losing bytes."""
    remaining = str(text or "")
    chunks = []
    limit = max(1, int(limit))
    while len(remaining) > limit:
        cut = remaining.rfind("\n\n", 0, limit + 1)
        if cut >= limit // 2:
            cut += 2
        else:
            cut = remaining.rfind("\n", 0, limit + 1)
            if cut >= limit // 2:
                cut += 1
            else:
                cut = remaining.rfind(" ", 0, limit + 1)
                cut = cut + 1 if cut >= limit // 2 else limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining or not chunks:
        chunks.append(remaining)
    return chunks


def _structured_youtube_text_html(text: str) -> str:
    """Turn shared YouTube text into a small, complete rich-reader DOM.

    A paragraph/heading node per subtitle cue and comment made WebView layout
    scale with the number of blocks (hundreds of thousands on popular videos).
    Keep the four navigable section headings and use moderately sized text
    leaves.  This avoids both thousands of cue/comment nodes and a single
    multi-megabyte accessibility object, while retaining every character.
    """
    blocks = [block.strip() for block in re.split(r"\n{2,}", str(text or "")) if block.strip()]
    heading_re = re.compile(r"^(?:Description|Chapters|Comments|Subtitles(?: \(.+\))?)$")
    sections = []
    heading = ""
    content = []
    for block in blocks:
        if heading_re.fullmatch(block):
            if heading:
                sections.append((heading, content))
            heading = block
            content = []
        else:
            content.append(block)
    if heading:
        sections.append((heading, content))

    output = []
    for section_heading, section_content in sections:
        output.append(f"<h2>{_html.escape(section_heading)}</h2>")
        joined = "\n\n".join(section_content)
        for chunk in _accessible_text_chunks(joined):
            output.append(
                '<div class="awv-youtube-section" style="white-space: pre-wrap">'
                f"{_html.escape(chunk)}</div>"
            )
    return "".join(output)


def render_full_article_html(
    url: str,
    *,
    fallback_html: str = "",
    fallback_title: str = "",
    fallback_author: str = "",
    date: str = "",
    timeout: int = 20,
    feed_lang: str = "",
    feed_item_lang: str = "",
    translation_target: str = "",
    max_pages: int = 6,
) -> Optional[str]:
    """Fetch ``url`` and return a full rich-reader HTML fragment (header + body).

    Multi-page articles (e.g. GSM Arena phone reviews split across "next page"
    links) are followed and their cleaned bodies concatenated, mirroring the
    plain-text reader's ``extract_full_article`` — the rich reader used to show
    only page 1 while the classic full-text view showed the whole story.

    Falls back to cleaned feed content when the page can't be fetched or yields
    no usable body. Returns None only when there is nothing at all to show.

    The returned ``<article>`` carries a ``lang`` attribute resolved by issue
    #72's priority order (translation target > source page > feed > UI
    language), so assistive tech picks the right voice, Braille table and text
    direction for the content instead of always assuming English.
    """
    from core import article_extractor as ae  # lazy: avoid import cycle at load

    url = (url or "").strip()
    title = str(fallback_title or "")
    author = str(fallback_author or "")
    body = ""
    page_lang = None  # source page's <html lang>, when the fetch succeeds
    display_url = url  # publisher URL once a Google News redirect is resolved
    metered_preview = False  # page served only the free excerpt (e.g. NYT)
    structured_youtube = False

    if url and ae._looks_like_id3_media_url(url) and not fallback_html.strip():
        # Direct podcast enclosure: preserve links from bounded embedded ID3
        # show notes.  The normal cleaner below sanitizes this publisher-owned
        # HTML before it reaches WebView.
        try:
            article = ae.extract_full_article(url, max_pages=1, timeout=timeout)
        except Exception:
            article = None
        if article:
            title = article.title or title
            author = article.author or author
            if article.html:
                body = clean_article_html(article.html, url, use_traf_prune=False)
            if not body and article.text:
                body = "".join(
                    f"<p>{_html.escape(block)}</p>"
                    for block in re.split(r"\n{2,}", article.text)
                    if block.strip()
                )

    if url and not ae._looks_like_media_url(url):
        # Use the exact same complete YouTube reconstruction as classic full
        # text. Cleaning the watch-page DOM would lose subtitles, comments, and
        # collapsed replies in Rich View even though the plain reader had them.
        try:
            from core import youtube_fulltext

            structured_youtube = youtube_fulltext.is_youtube_video_url(url)
        except Exception:
            structured_youtube = False
        if structured_youtube:
            try:
                article = ae.extract_full_article(url, max_pages=1, timeout=timeout)
            except Exception:
                article = None
            if article:
                title = article.title or title
                author = article.author or author
                body = _structured_youtube_text_html(article.text)

        # Google News feed items are signed redirects, not publisher pages.
        # Resolve to the real article URL first (same as the plain-text path),
        # or the fetch below would clean Google's redirect/consent shell.
        fetch_url = url
        if ae._is_google_news_article_url(url):
            resolved = ae._resolve_google_news_article_url(url, timeout)
            fetch_url = resolved or ""
            if resolved:
                display_url = resolved

        if fetch_url and not structured_youtube:
            # Follow simple pagination (rel=next / "next page" controls) and
            # concatenate each page's cleaned body — the same _find_next_page
            # the plain-text extractor uses, so host exclusions and next-STORY
            # guards apply identically. Without this the rich reader stopped at
            # page 1 of multi-page articles (e.g. GSM Arena reviews) while the
            # classic full-text view rendered the whole story.
            body_parts: list = []
            seen_sigs: set = set()
            visited: set = set()
            current = fetch_url
            harvested_meta = False
            for _ in range(max(1, max_pages)):
                if not current or current in visited:
                    break
                visited.add(current)
                try:
                    res = ae._fetch_page(current, timeout=timeout)
                    page_html = res.html or ""
                except Exception:
                    page_html = ""
                if not page_html:
                    break
                if not harvested_meta:
                    harvested_meta = True
                    t, a = ae._extract_title_author_from_meta(page_html, current)
                    title = title or t
                    author = author or a
                    # Read the source page's declared language before cleaning:
                    # the cleaner keeps only the body, so <html lang> is gone
                    # after it. Only page 1's language is authoritative.
                    page_lang = article_lang.lang_from_page_html(page_html)
                    metered_preview = ae._looks_like_metered_preview(page_html)
                expanded_html = ae._expand_sky_flourish_tables(page_html, current, timeout)
                expanded_html = ae._normalize_gsmarena_battery_table_html(
                    expanded_html, current
                )
                page_body = clean_article_html(expanded_html, current)
                if page_body:
                    # De-dupe whole pages by normalized text: some sites' "next"
                    # control eventually loops back to already-seen content, and
                    # the page must not be appended twice.
                    sig = _norm(BeautifulSoup(page_body, "html.parser").get_text(" ", strip=True))
                    if sig and sig not in seen_sigs:
                        seen_sigs.add(sig)
                        body_parts.append(page_body)
                next_url = ae._find_next_page(page_html, current)
                if not next_url or next_url in visited:
                    break
                current = next_url
                time.sleep(0.15)
            body = "".join(body_parts)

        # Blocked/unresolvable Google News: fall back to the read-proxy rendering
        # (text only, no embeds) so the article still shows, like the text path.
        if not body and ae._is_google_news_article_url(url) and ae._google_news_article_token(url):
            try:
                proxy_md = ae._download_via_jina(url, timeout)
            except Exception:
                proxy_md = None
            if proxy_md and not ae._looks_like_bot_interstitial(proxy_md):
                text = ae._strip_edge_nav_runs(
                    ae._strip_proxy_trailing_boilerplate(ae._markdown_links_to_text(proxy_md))
                ).strip()
                if text:
                    body = "".join(
                        f"<p>{_html.escape(block)}</p>"
                        for block in re.split(r"\n{2,}", text)
                        if block.strip()
                    )

    # Some publishers (e.g. fraservalleytoday.ca) serve a truncated web page but
    # syndicate the complete story in the feed. Prefer whichever body is fuller,
    # never downgrading below the feed content the user could already see.
    # Never for a GitHub page: it is rebuilt whole from the API, so the feed item (the
    # pull-request description alone) must not be able to replace the conversation.
    if fallback_html and not structured_youtube and not ae._is_github_page_url(url):
        feed_body = clean_article_html(fallback_html, display_url, use_traf_prune=False)
        if feed_body:
            body_len = len(_norm(BeautifulSoup(body or "", "html.parser").get_text(" ", strip=True)))
            feed_len = len(_norm(BeautifulSoup(feed_body, "html.parser").get_text(" ", strip=True)))
            if feed_len > body_len * 1.25:
                embeds = "".join(_harvest_embeds_html(BeautifulSoup(body or "", "html.parser")))
                body = feed_body + embeds
                # The feed carried more than the page did, so the free-excerpt
                # notice no longer describes what is being shown.
                metered_preview = False

    if not body:
        body = _feed_fallback_html(fallback_html, display_url)
        metered_preview = False
    if not body:
        return None
    # Metered publishers (NYT) serve a few paragraphs and withhold the rest. Without
    # this the story just stops, and the subscribe note that explains it has been
    # stripped as chrome.
    if metered_preview:
        body += f'<p class="awv-notice">{_html.escape(ae.metered_preview_notice())}</p>'

    header_bits = [f"<h1>{_html.escape(title.strip() or display_url or '')}</h1>"]
    meta_line = " · ".join(
        p for p in (str(date or "").strip(), (author or "").strip()) if p
    )
    if meta_line:
        header_bits.append(f'<p class="awv-meta">{_html.escape(meta_line)}</p>')
    if display_url:
        safe_url = _html.escape(display_url, quote=True)
        header_bits.append(
            f'<p class="awv-source"><a href="{safe_url}">{_html.escape(display_url)}</a></p>'
        )
    header = "".join(header_bits)
    # lang goes on <article> (the "relevant container" issue #72 allows) rather
    # than <html>: the document skeleton is created once by the webview library
    # and reused for every article, so the root cannot follow per-article
    # language. lang on an ancestor applies to its whole subtree, so the content
    # is announced correctly either way.
    lang = article_lang.resolve_content_language(
        translation_target=translation_target or None,
        page_lang=page_lang,
        feed_item_lang=feed_item_lang or None,
        feed_lang=feed_lang or None,
    )
    return f'<article lang="{_html.escape(lang, quote=True)}">{header}<hr>{body}</article>'
