# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""File > Open Article: read any web page in BlindRSS's own article reader.

The article list only reaches what a subscribed feed still lists, so a story a
friend sends over — or one whose own site is unreadable behind cookie walls,
ad interstitials and infinite scroll — had nowhere to go. This command takes a
pasted address and shows it in one of the two readers the app already has: the
plain full-text view, or the rich HTML view.

This module is the GUI-free half: what counts as a usable address, which
renderer runs, and — the part that matters for a screen-reader user — what the
window says when the page cannot be read. A failed load never leaves an empty
reader; it returns readable text explaining what happened, in the same shape
the successful load returns, so the window has exactly one thing to display.

``gui.article_window`` owns the window, ``gui.dialogs.OpenArticleDialog`` asks
for the address and which reader to use.
"""

from __future__ import annotations

import html as html_stdlib
import logging
import re
from collections import namedtuple

from core import article_extractor
from core import article_html
from core import media_url
from core.i18n import _

log = logging.getLogger(__name__)

# Longer than the reader pane's 20s: this is a deliberate, user-initiated read
# of one page with a window already open and saying "Loading", not a background
# prefetch competing with the rest of a refresh.
DEFAULT_TIMEOUT_S = 30

#: What one call to :func:`load_article` produced.
#:
#: ``content`` is always non-empty and always matches ``rich`` (an HTML
#: fragment when rich, plain text otherwise), success or failure — the window
#: renders it either way. ``ok`` says whether it is the article or an
#: explanation, which is what decides the announcement the reader hears.
LoadedArticle = namedtuple("LoadedArticle", "url rich ok title content")


def normalize_article_url(text) -> str:
    """Clean a pasted string into an http(s) URL, or "" when it is not one.

    Deliberately the same function the Open Media URL command uses: "is this a
    web address the app can fetch" must have one definition, and everything
    ``media_url`` rejects (search phrases, local paths, mailto:/magnet: links)
    is just as unfetchable here.
    """
    return media_url.normalize_media_url(text)


def _strip_tags(fragment: str) -> str:
    return html_stdlib.unescape(re.sub(r"<[^>]+>", " ", str(fragment or ""))).strip()


def title_from_rendered_html(fragment: str) -> str:
    """The <h1> the rich renderer wrote, for the window's caption."""
    match = re.search(r"<h1[^>]*>(.*?)</h1>", str(fragment or ""), re.I | re.S)
    if not match:
        return ""
    return " ".join(_strip_tags(match.group(1)).split())


def title_from_rendered_text(rendered: str) -> str:
    """The title line the plain renderer wrote, for the window's caption.

    ``render_full_article`` prefixes its output with a translated "Title:"
    line, so the prefix is matched from the same catalog that wrote it rather
    than by hard-coded English.
    """
    lines = str(rendered or "").strip().splitlines()
    if not lines:
        return ""
    first = lines[0].strip()
    prefix = _("Title:")
    if not first.startswith(prefix):
        return ""
    title = first[len(prefix):].strip()
    return "" if title == _("(unknown)") else title


def failure_text(url: str, reason: str = "") -> str:
    """Plain-text stand-in shown when the page could not be read."""
    parts = [_("This page could not be read.")]
    if reason:
        parts.append(reason)
    if url:
        parts.append(_("Address:") + f" {url}")
    parts.append(
        _("Try opening it in your browser, or import that site's cookies from "
          "Tools > Import Site Cookies if it is behind a check.")
    )
    return "\n\n".join(parts) + "\n"


def failure_html(url: str, reason: str = "") -> str:
    """The same explanation as an HTML fragment, for the rich reader.

    Kept as a real ``<article>`` with an ``<h1>`` so the rich view's heading
    navigation still lands somewhere and the window's caption logic finds a
    title, rather than reading an empty document.
    """
    escape = html_stdlib.escape
    body = f"<h1>{escape(_('This page could not be read.'))}</h1>"
    if reason:
        body += f"<p>{escape(reason)}</p>"
    if url:
        safe = escape(url, quote=True)
        body += f'<p><a href="{safe}">{escape(url)}</a></p>'
    body += (
        "<p>"
        + escape(
            _("Try opening it in your browser, or import that site's cookies "
              "from Tools > Import Site Cookies if it is behind a check.")
        )
        + "</p>"
    )
    return f"<article>{body}</article>"


def _failed(url: str, rich: bool, reason: str) -> LoadedArticle:
    return LoadedArticle(
        url=url,
        rich=rich,
        ok=False,
        title="",
        content=failure_html(url, reason) if rich else failure_text(url, reason),
    )


def _reason_from(error: BaseException) -> str:
    """One readable line out of an extraction failure.

    ``ExtractionError`` already carries the user-facing guidance the reader
    pane shows for a blocked or paywalled page, so it is passed through rather
    than replaced with a generic message; anything else is collapsed and
    trimmed so a stack-shaped repr cannot become the window's whole content.
    """
    reason = " ".join(str(error or "").split()).strip()
    if not reason:
        return ""
    return reason if len(reason) <= 400 else reason[:397].rstrip() + "..."


def load_article(url, *, rich: bool = True, timeout: int = DEFAULT_TIMEOUT_S) -> LoadedArticle:
    """Fetch one web page and render it for the reader that ``rich`` chooses.

    Runs the network, so callers must call it off the UI thread. It never
    raises: every failure comes back as a ``LoadedArticle`` with ``ok`` False
    and readable ``content``.
    """
    normalized = normalize_article_url(url)
    if not normalized:
        return _failed(
            str(url or "").strip(),
            rich,
            _("That does not look like a web address. Enter a full address, "
              "for example https://example.com/story."),
        )

    rendered = None
    reason = ""
    try:
        if rich:
            rendered = article_html.render_full_article_html(normalized, timeout=timeout)
        else:
            rendered = article_extractor.render_full_article(
                normalized, prefer_feed_content=False, timeout=timeout
            )
    except Exception as error:  # ExtractionError and anything under it
        log.info("Open Article could not read %s: %s", normalized, error)
        reason = _reason_from(error)

    if not (rendered and str(rendered).strip()):
        return _failed(normalized, rich, reason)

    rendered = str(rendered)
    title = (
        title_from_rendered_html(rendered) if rich else title_from_rendered_text(rendered)
    )
    return LoadedArticle(url=normalized, rich=rich, ok=True, title=title, content=rendered)
