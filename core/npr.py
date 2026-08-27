# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""NPR-specific routing around the TollBit pay-per-crawl gate.

npr.org put its article pages behind TollBit metering, which answers any client it
does not recognize as a person's browser with HTTP 402 and a short JSON body:

    [{"message":"You are not authorized to access this content without a valid
      TollBit Token. ...","url":"https://tollbit.dev", ...}]

The gate is applied by client reputation rather than by TLS fingerprint — measured
against all 19 curl_cffi impersonation targets (every Chrome, Safari, Firefox and
Edge hello available), every one of which was refused while the gate was up, and all
of which were served while it was down. So there is no fingerprint to hide behind and
no interactive challenge a cookie import could clear; the reader simply must not go
through www.npr.org for story pages.

Two NPR-run routes are outside the gate and are what this module uses instead:

* ``text.npr.org/<story id>`` — NPR's own text-only edition. It returns the complete
  story (including the full radio transcript, which the main site loads separately),
  with no navigation, ads or player chrome, which makes it the better source for the
  reader even when the gate happens to be down.
* ``www.npr.org/player/embed/<story id>/<story id>`` — the audio player NPR serves for
  syndication. It carries the on-demand MP3 for stories whose feed entry has no
  enclosure (feeds.npr.org/2/rss.xml is the reported case: its items ship a
  description and nothing else).

Both are keyed by the story ID that already appears in every npr.org article URL.
"""

import re
import html as html_module
import json
import logging
from urllib.parse import urlsplit
from bs4 import BeautifulSoup, NavigableString
from core import utils

log = logging.getLogger(__name__)

# NPR story IDs are either the current CMS form (nx-s1-5923944, sometimes with an
# edition suffix: nx-s1-5921392-e1) or a legacy all-digit ID (1173000000). Matching
# these shapes rather than "any path segment" keeps a slug from being mistaken for an
# ID, which would send the reader to a text.npr.org page for a different story.
_STORY_ID_RE = re.compile(r"(?:nx-[a-z0-9]+-[0-9]+(?:-[a-z0-9]+)*|\d{6,})\Z", re.I)

# text.npr.org renders NPR's inline "related story" insets as a bare label followed by
# a link whose only text is the site name, fenced by a horizontal rule on each side:
#
#     <hr> Related Story: <a href="/150009152">NPR</a> <hr>
#
# The full site puts the related headline in that link; the text edition never does
# (checked against every inset across the current NPR feeds - the anchor text was
# "NPR" every time). So the inset reaches the reader pane as a content-free
# "Related Story: NPR" line interrupting the article one to five times. Drop it.
_RELATED_STORY_LABEL_RE = re.compile(r"related\s+story\s*:\s*\Z", re.I)

# The on-demand MP3 inside the embed player lives in a JSON blob, so its slashes may be
# escaped (https:\/\/ondemand.npr.org\/...). Accept both forms and unescape after.
_ONDEMAND_MP3_RE = re.compile(
    r'https?:(?:\\?/){2}ondemand\.npr\.org(?:[^\s"\'<>]|\\/)+?\.mp3(?:[^\s"\'<>]|\\/)*'
)

_TEXT_HOST = "text.npr.org"


def is_npr_url(url: str) -> bool:
    if not url:
        return False
    return "npr.org" in url.lower()


def story_id_from_url(url: str) -> str:
    """The NPR story ID in an article URL, or "" when this is not a story URL.

    Handles the shapes NPR's feeds and site actually produce:
        /2026/08/12/<id>/<slug>
        /sections/<section>/2026/08/12/<id>/<slug>
        /transcripts/<id>
        /<id>                       (the "Go To Full Site" short form)
        /templates/story/story.php?storyId=<id>
    """
    if not is_npr_url(url):
        return ""
    try:
        parts = urlsplit(str(url))
    except Exception:
        return ""
    host = (parts.hostname or "").lower()
    # text.npr.org is already the destination; re-routing it would loop.
    if host == _TEXT_HOST:
        return ""
    segments = [s for s in parts.path.split("/") if s]

    # Dated paths: the ID is the segment straight after YYYY/MM/DD.
    for index, segment in enumerate(segments):
        if re.fullmatch(r"\d{4}", segment) and index + 3 < len(segments):
            candidate = segments[index + 3]
            if _STORY_ID_RE.fullmatch(candidate):
                return candidate

    # /transcripts/<id> and the bare /<id> short form.
    if len(segments) == 2 and segments[0].lower() == "transcripts":
        if _STORY_ID_RE.fullmatch(segments[1]):
            return segments[1]
    if len(segments) == 1 and _STORY_ID_RE.fullmatch(segments[0]):
        return segments[0]

    # Legacy template URLs carry the ID in the query string. urlsplit strips the leading
    # "?", so the first parameter has no separator in front of it.
    match = re.search(r"(?:\A|&)storyId=([^&]+)", parts.query, re.I)
    if match and _STORY_ID_RE.fullmatch(match.group(1)):
        return match.group(1)
    return ""


def text_only_url(url: str) -> str:
    """The ungated text.npr.org URL for an npr.org story, or "" if there is none."""
    story_id = story_id_from_url(url)
    return f"https://{_TEXT_HOST}/{story_id}" if story_id else ""


def _visible_sibling(node, forward: bool):
    """The nearest sibling of ``node`` that is not a whitespace-only text node."""
    sibling = node.next_sibling if forward else node.previous_sibling
    while isinstance(sibling, NavigableString) and not str(sibling).strip():
        sibling = sibling.next_sibling if forward else sibling.previous_sibling
    return sibling


def strip_related_story_stubs(html: str) -> str:
    """Remove text.npr.org's content-free "Related Story: NPR" insets (see above)."""
    if not html or "Related Story" not in html:
        return html
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return html
    removed = False
    for link in soup.find_all("a"):
        if link.get_text(strip=True).upper() != "NPR":
            continue
        label = _visible_sibling(link, forward=False)
        if not isinstance(label, NavigableString):
            continue
        text = str(label)
        if not _RELATED_STORY_LABEL_RE.search(text):
            continue
        # The rules exist only to fence the inset off from the paragraphs around it,
        # so they go with it rather than leaving two bare separators behind.
        for rule in (_visible_sibling(label, forward=False), _visible_sibling(link, forward=True)):
            if getattr(rule, "name", "") == "hr":
                rule.extract()
        # The label is its own text node on every page NPR serves; if it ever trails
        # real prose, keep the prose and drop only the label.
        kept = _RELATED_STORY_LABEL_RE.sub("", text)
        if kept.strip():
            label.replace_with(soup.new_string(kept))
        else:
            label.extract()
        link.extract()
        removed = True
    return str(soup) if removed else html


def download_text_only_html(url: str, timeout: int = 20) -> str:
    """Fetch an NPR story from the text-only edition. Returns "" when unavailable.

    Fails closed on purpose: an empty return sends the caller back to its normal fetch
    chain rather than showing the reader a half-page.
    """
    target = text_only_url(url)
    if not target:
        return ""
    try:
        response = utils.safe_requests_get(target, timeout=timeout, allow_redirects=True)
    except Exception as e:
        log.debug(f"NPR text-only fetch failed for {target}: {e}")
        return ""
    if not (200 <= response.status_code < 400):
        log.debug(f"NPR text-only fetch refused for {target}: HTTP {response.status_code}")
        return ""
    # Decode the bytes through the shared chain (header charset -> meta charset -> utf-8)
    # rather than trusting requests, whose charset-less default is ISO-8859-1 and would
    # turn NPR's curly quotes and em dashes into mojibake (issue #75).
    try:
        from core import text_encoding

        html = text_encoding.decode_bytes(
            response.content,
            override="",
            content_type=str(response.headers.get("Content-Type", "") or ""),
            kind="html",
        )
    except Exception:
        html = response.text or ""
    # The text edition serves the same shell for an unknown ID, so require the story body
    # rather than trusting the status code.
    if "paragraphs-container" not in html:
        log.debug(f"NPR text-only page for {target} carried no story body")
        return ""
    return strip_related_story_stubs(html)


def _audio_from_embed_player(story_id: str, timeout_s: float) -> str | None:
    """The on-demand MP3 from NPR's syndication player, which TollBit does not meter."""
    if not story_id:
        return None
    embed_url = f"https://www.npr.org/player/embed/{story_id}/{story_id}"
    try:
        response = utils.safe_requests_get(embed_url, timeout=timeout_s, allow_redirects=True)
    except Exception as e:
        log.debug(f"NPR embed player fetch failed for {embed_url}: {e}")
        return None
    if not (200 <= response.status_code < 400):
        log.debug(f"NPR embed player refused for {embed_url}: HTTP {response.status_code}")
        return None
    match = _ONDEMAND_MP3_RE.search(response.text or "")
    if not match:
        return None
    return html_module.unescape(match.group(0).replace("\\/", "/"))


def extract_npr_audio(url: str, timeout_s: float = 10.0) -> tuple[str | None, str | None]:
    """
    Extracts the audio URL and type from an NPR story page.
    Returns (audio_url, audio_type).
    """
    if not is_npr_url(url):
        return None, None

    try:
        # The syndication player first: it is the only route that keeps working while
        # TollBit is metering, and it costs the same single request the story page did.
        # This runs during feed refresh, once per NPR article, so the whole function
        # stays at one request in the common case and never escalates to the read-proxy
        # or headless-browser chain that full-text extraction can afford.
        embed_audio = _audio_from_embed_player(story_id_from_url(url), timeout_s)
        if embed_audio:
            return embed_audio, "audio/mpeg"

        # Fall back to the story page for anything the player does not cover. This is
        # the gated route, so it is expected to fail whenever TollBit is metering.
        try:
            resp = utils.safe_requests_get(url, timeout=timeout_s, allow_redirects=True)
        except Exception as e:
            log.debug(f"NPR story page fetch failed for {url}: {e}")
            return None, None
        if not (200 <= resp.status_code < 400):
            log.debug(f"NPR story page refused for {url}: HTTP {resp.status_code}")
            return None, None
        html = resp.text or ""
        soup = BeautifulSoup(html, "html.parser")

        # 1. Try finding data-audio JSON (New NPR CMS / Brightspot)
        # Often in <div class="audio-module-controls-wrap" data-audio='...'>
        node = soup.find(attrs={"data-audio": True})
        if node:
            try:
                raw_json = str(node["data-audio"])
                data = json.loads(raw_json)
                audio_url = data.get("audioUrl")
                if audio_url:
                    # Unescape backslashes if any (though json.loads handles standard escapes)
                    # NPR sometimes has double-escaped slashes in raw strings if scraped via regex,
                    # but via soup it should be clean. Just to be safe:
                    if "\\/" in audio_url:
                        audio_url = audio_url.replace("\\/", "/")
                    return audio_url, "audio/mpeg"
            except Exception as e:
                log.debug(f"NPR data-audio JSON parse failed: {e}")

        # 2. Try finding download/listen link
        # <a class="audio-module-listen" href="...">
        link = soup.find("a", class_="audio-module-listen")
        if link and link.get("href"):
            href = str(link["href"])
            if ".mp3" in href:
                return href, "audio/mpeg"

        # 3. Fallback: Search for any link containing .mp3 from ondemand.npr.org
        # This is a bit looser but helps with older layouts.
        for a in soup.find_all("a", href=True):
            href = str(a["href"])
            if "ondemand.npr.org" in href and ".mp3" in href:
                return href, "audio/mpeg"

        # 4. Last resort: the media URL is present but not in an element this function
        # knows how to read (an inline player config, a JSON island, a data- attribute
        # NPR renamed). Take it straight out of the raw markup, unescaping the query
        # string so the signing/segment parameters the player needs survive.
        raw_match = _ONDEMAND_MP3_RE.search(html)
        if raw_match:
            return html_module.unescape(raw_match.group(0).replace("\\/", "/")), "audio/mpeg"

    except Exception as e:
        log.warning(f"NPR audio extraction failed for {url}: {e}")

    return None, None
