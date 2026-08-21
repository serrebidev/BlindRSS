# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""System-browser link handling for the rich (WebView) article readers.

``wx_accessible_webview``'s ``open_links_externally`` option vetoes *every*
``wxEVT_WEBVIEW_NAVIGATING`` and hands the URL to the system browser. That was
right while wx reported only top-level navigations, but wxWidgets 3.3 also
fires the event for sub-frames — so an article's YouTube/X ``<iframe>`` embed
looked exactly like a link click: it was vetoed and popped open in a browser
window instead of rendering inline (issue #102).

The readers therefore build the view with ``open_links_externally=False`` and
call :func:`attach` instead. It diverts only navigations of the main frame —
which are always link clicks, since the article body is written with innerHTML
and never navigates — plus the pop-ups embeds ask for via ``window.open`` or
``target="_blank"``. Everything else, iframes included, loads in the WebView.
"""

from __future__ import annotations

import logging
import webbrowser
from urllib.parse import urlsplit

log = logging.getLogger(__name__)

# wx.html2.WEBVIEW_NAV_ACTION_USER. Keep the small value local so this
# GUI-free decision logic stays testable without importing wx.html2.
_USER_NAVIGATION_ACTION = 1


def external_url(href) -> str | None:
    """Return ``href`` when it is a plain HTTP(S) URL safe to hand to the OS."""
    value = str(href or "")
    if not value or "\\" in value:
        return None
    if any(ch.isspace() or ord(ch) < 32 or 127 <= ord(ch) <= 159 for ch in value):
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme.lower() not in ("http", "https"):
            return None
        if not parsed.hostname:
            return None
        if parsed.username is not None or parsed.password is not None:
            return None
        parsed.port
    except (TypeError, ValueError):
        return None
    return value


def targets_main_frame(event) -> bool:
    """True when a NAVIGATING event is about the top-level document."""
    is_main = getattr(event, "IsTargetMainFrame", None)
    if callable(is_main):
        try:
            return bool(is_main())
        except Exception:
            log.debug("IsTargetMainFrame() failed", exc_info=True)
    # wxWidgets < 3.3 has neither IsTargetMainFrame() nor sub-frame navigation
    # events, so anything that reaches us there is already the main frame; a
    # named target, if the backend reports one, still names a sub-frame.
    try:
        return not (event.GetTarget() or "")
    except Exception:
        return True


def user_initiated(event) -> bool:
    """True only for an explicit link activation when wx reports the action."""
    get_action = getattr(event, "GetNavigationAction", None)
    if not callable(get_action):
        return True
    try:
        return int(get_action()) == _USER_NAVIGATION_ACTION
    except Exception:
        return False


def navigation_target(event) -> str | None:
    """The URL a NAVIGATING event should open externally, or None to let it be."""
    if not user_initiated(event):
        return None
    if not targets_main_frame(event):
        return None
    try:
        url = event.GetURL()
    except Exception:
        return None
    return external_url(url)


def _open(url: str, opener=None) -> None:
    try:
        (opener or webbrowser.open)(url)
    except Exception:
        log.debug("Failed to open %s in the system browser", url, exc_info=True)


def make_navigating_handler(opener=None):
    """Handler that sends main-frame link clicks to the system browser."""

    def _on_navigating(event):
        url = navigation_target(event)
        if url is None:
            return
        try:
            event.Veto()
        except Exception:
            log.debug("Failed to veto navigation to %s", url, exc_info=True)
        _open(url, opener)

    return _on_navigating


def make_new_window_handler(opener=None):
    """Handler for pop-ups (``window.open`` / ``target="_blank"``).

    wx does nothing with these unless the app acts, so an embed's "Watch on
    YouTube" would otherwise be a dead click. There is no frame to keep them
    in, so the system browser is the right home for them.
    """

    def _on_new_window(event):
        if not user_initiated(event):
            return
        try:
            url = event.GetURL()
        except Exception:
            return
        safe_url = external_url(url)
        if safe_url is not None:
            _open(safe_url, opener)

    return _on_new_window


def attach(view, opener=None) -> bool:
    """Bind the link handlers to a ``wx.html2.WebView``. True when bound."""
    if view is None:
        return False
    try:
        import wx.html2 as webview2
    except Exception:
        return False
    try:
        view.Bind(webview2.EVT_WEBVIEW_NAVIGATING, make_navigating_handler(opener))
        view.Bind(webview2.EVT_WEBVIEW_NEWWINDOW, make_new_window_handler(opener))
    except Exception:
        log.debug("Failed to bind rich-view link handlers", exc_info=True)
        return False
    return True
